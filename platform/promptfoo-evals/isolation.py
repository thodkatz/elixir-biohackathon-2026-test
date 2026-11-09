"""Snapshot and restore of the instance's mutable state, the state baseline and diff, and the promptfoo hook.

    extensions: [file://isolation.py:extension_hook]

Spec part 05. Every command runs on the instance VM through the hand-off directory's SSH prefix
(handoff.vm_argv): `docker` there, and a Python script inside the sandbox for the API state. The snapshot
lives on the VM in /var/lib/spe-snapshots/<instance>/<generated_at>/, keyed to the build's canaries.json,
so a re-provisioned instance never restores an older build. Standard library only.

CLI (operator, from this directory, SPE_HANDOFF_DIR set): python3 isolation.py snapshot|exists|restore|sh
"""
from __future__ import annotations

import json
import os
import re
import shlex
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from handoff import ConfigError, handoff_dir, vm_argv

SNAPSHOT_ROOT = "/var/lib/spe-snapshots"
VOLUMES = ("workflow-stack_wes-mongodb", "workflow-stack_redis-data", "workflow-stack_weskit-data",
           "workflow-stack_weskit-workflows", "workflow-stack_trs-mongodb", "workflow-stack_drs-mongodb",
           "spe-frontend_open-terminal-data")
NOT_RESTORED = {"workflow-stack_slurm-master-var": "declared, mounted by no service",
                "workflow-stack_slurm-master-spool": "declared, mounted by no service",
                "spe-frontend_agent-runs": "the agent's run log, which the agent cannot read (part 05)",
                "spe-frontend_chat-sessions": "the chat UI's sessions; evaluations call the agent directly, "
                                              "never chat-ui (part 05)",
                "spe-frontend_open-webui-data": "Open WebUI's database; ladder levels run spe_frontends: [agui]",
                "spe-frontend_chat-ui-node-modules": "the ui-dev chat UI's build cache, not on the agent path",
                "spe-frontend_chat-ui-next": "the ui-dev chat UI's build cache, not on the agent path"}
SANDBOX = "spe-frontend-sandbox-1"
# Databases first; recreated per Compose project (compose_projects), which orders them by depends_on.
CONTAINERS = tuple(f"workflow-stack-{s}-1" for s in (
    "database", "result_broker", "trs-mongodb", "drs-mongodb", "rest", "submission_worker",
    "monitoring_worker", "monitoring_scheduler", "trs-filer", "drs-filer")) + (SANDBOX,)
SSH_MUX = ["-o", "ControlMaster=auto", "-o", "ControlPath=~/.ssh/spe-eval-%C", "-o", "ControlPersist=120"]
HEALTH_FMT = "{{.Name}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}"
LABELS_FMT = "|".join(["{{.Name}}"] + [f'{{{{index .Config.Labels "com.docker.compose.{k}"}}}}' for k in
                                       ("project", "project.working_dir", "project.config_files", "service")])
API_CHECK = ('for u in "$TRS_BASE/service-info" "$WES_BASE/service-info" "$DRS_BASE/service-info"; do '
             'curl -s -o /dev/null -w "%{http_code} " "$u"; done')
SNAP_SH = ('set -eu; d="/s/$1/$2"; rm -rf "/s/$1"; mkdir -p "$d"; '
           'for v in /v/*; do tar -cf "$d/$(basename "$v").tar" -C "$v" .; done; echo "$2" > "$d/COMPLETE"')
RESTORE_SH = ('set -eu; d="/s/$1/$2"; for v in /v/*; do n=$(basename "$v"); test -f "$d/$n.tar"; '
              'find "$v" -mindepth 1 -delete; tar -xpf "$d/$n.tar" -C "$v"; done')
_INSTANCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}")
_STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")

Runner = Callable[..., subprocess.CompletedProcess]


class IsolationError(RuntimeError):
    """The stack's state could not be saved, put back or read: never continue on it."""


class RestoreError(IsolationError):
    pass


def _image() -> str:
    return os.environ.get("SPE_SNAPSHOT_IMAGE", "alpine:3.20")


def vm_runner(directory: Path) -> Runner:
    """Runs argv on the VM: the hand-off's SSH prefix, one multiplexed connection, argv quoted for the remote shell."""
    prefix = vm_argv(directory)
    if prefix and prefix[0] == "ssh":
        prefix = [prefix[0], *SSH_MUX, *prefix[1:]]

    def run(argv: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
        full = [*prefix, shlex.join(argv)] if prefix else list(argv)
        return subprocess.run(full, input=stdin, capture_output=True, text=True, timeout=900)

    return run


def _ok(proc: subprocess.CompletedProcess, what: str, error=RestoreError) -> subprocess.CompletedProcess:
    if proc.returncode == 255:
        raise error(f"{what}: the VM is unreachable (exit 255); check hosts.yml before retrying")
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-300:]
        raise error(f"{what} failed (exit {proc.returncode}): {tail}")
    return proc


def snapshot_key(directory: Path) -> tuple[str, str]:
    path = Path(directory) / "canaries.json"
    try:
        record = json.loads(path.read_text())
    except FileNotFoundError:
        raise ConfigError(f"{path} missing (decrypt canaries.json.age first if the record is encrypted)") from None
    except ValueError:
        raise ConfigError(f"{path} is not JSON") from None
    instance, stamp = record.get("instance"), record.get("generated_at")
    if not isinstance(instance, str) or not _INSTANCE.fullmatch(instance):
        raise ConfigError(f"{path}: invalid instance name")
    if not isinstance(stamp, str) or not _STAMP.fullmatch(stamp):
        raise ConfigError(f"{path}: invalid generated_at")
    return instance, stamp.replace(":", "")


def _mounts(mode: str) -> list[str]:
    return [arg for vol in VOLUMES for arg in ("-v", f"{vol}:/v/{vol}{mode}")]


def _require_volumes(run: Runner) -> None:
    _ok(run(["docker", "volume", "inspect", "--format", "{{.Name}}", *VOLUMES]),
        "checking the volumes (renamed in compose? update isolation.VOLUMES)")


def snapshot_exists(directory: Path, run: Runner | None = None) -> bool:
    run = run or vm_runner(directory)
    instance, key = snapshot_key(directory)
    proc = run(["docker", "run", "--rm", "-v", f"{SNAPSHOT_ROOT}:/s:ro", _image(),
                "test", "-f", f"/s/{instance}/{key}/COMPLETE"])
    if proc.returncode == 1:
        return False
    _ok(proc, "looking for the snapshot")
    return True


def wait_healthy(run: Runner, timeout: float = 300.0, clock=time.monotonic, sleep=time.sleep,
                 poll: float = 2.0) -> None:
    """Every container running (and healthy, if it has a health check), then TRS, WES and DRS answer 200."""
    deadline, last = clock() + timeout, "no check ran"
    while True:
        proc = _ok(run(["docker", "inspect", "-f", HEALTH_FMT, *CONTAINERS]), "inspecting the stack")
        bad = [line.split()[0].lstrip("/") for line in proc.stdout.splitlines()
               if line.split()[1:2] != ["running"] or line.split()[2:3] not in (["none"], ["healthy"])]
        if bad:
            last = "not running or not healthy: " + ", ".join(bad)
        else:
            codes = _ok(run(["docker", "exec", SANDBOX, "sh", "-c", API_CHECK]), "asking the APIs").stdout.split()
            if codes == ["200", "200", "200"]:
                return
            last = "APIs answered " + " ".join(codes or ["nothing"])
        if clock() >= deadline:
            raise RestoreError(f"stack not healthy after {timeout:.0f}s: {last}")
        sleep(poll)


def compose_projects(run: Runner) -> dict[str, tuple[str, list[str], list[str]]]:
    """Each container's Compose project, directory, files and service, from its labels: what recreating needs."""
    out = _ok(run(["docker", "inspect", "-f", LABELS_FMT, *CONTAINERS]), "reading the Compose labels").stdout
    projects: dict[str, tuple[str, list[str], list[str]]] = {}
    seen = set()
    for line in out.splitlines():
        name, project, workdir, files, service = (line.strip().lstrip("/").split("|") + [""] * 5)[:5]
        if not all((project, workdir, files, service)):
            raise RestoreError(f"{name}: no Compose labels (project, working_dir, config_files, service): "
                               "recreate it with docker compose first")
        entry = projects.setdefault(project, (workdir, files.split(","), []))
        entry[2].append(service)
        seen.add(name)
    missing = sorted(set(CONTAINERS) - seen)
    if missing:
        raise RestoreError(f"no such container: {', '.join(missing)}")
    return projects


def _cycle(run: Runner, argv: list[str], what: str) -> None:
    """Stop the stack, run one container over the volumes, then recreate the stack's containers from their images
    whatever happened: nothing written outside a volume (the sandbox's /tmp, a worker's writable layer) survives."""
    projects = compose_projects(run)
    _ok(run(["docker", "stop", "-t", "30", *CONTAINERS]), "stopping the stack")
    try:
        _ok(run(argv), what)
    finally:
        for project, (workdir, files, services) in projects.items():
            # --renew-anon-volumes also empties the MongoDB containers' anonymous volume (the mongo image's
            # VOLUME /data/configdb, checked live on de.NBI): unused by a standalone mongod, so not snapshotted.
            _ok(run(["docker", "compose", "--project-directory", workdir, "-p", project,
                     *[a for f in files for a in ("-f", f)], "up", "-d", "--force-recreate", "--renew-anon-volumes",
                     "--no-deps", "--no-build", "--pull", "never", *services]), f"recreating {project}")


def snapshot(directory: Path, run: Runner | None = None, timeout: float = 300.0,
             clock=time.monotonic, sleep=time.sleep) -> None:
    run = run or vm_runner(directory)
    instance, key = snapshot_key(directory)
    _require_volumes(run)
    _cycle(run, ["docker", "run", "--rm", *_mounts(":ro"), "-v", f"{SNAPSHOT_ROOT}:/s", _image(),
                 "sh", "-c", SNAP_SH, "snapshot", instance, key], "saving the volumes")
    wait_healthy(run, timeout, clock, sleep)


def restore(directory: Path, run: Runner | None = None, timeout: float = 300.0,
            clock=time.monotonic, sleep=time.sleep) -> float:
    """Put the build's snapshot back into every volume; returns the seconds it took. Raises, never skips."""
    run = run or vm_runner(directory)
    instance, key = snapshot_key(directory)
    start = clock()
    _require_volumes(run)
    if not snapshot_exists(directory, run):
        raise RestoreError(f"no complete snapshot of build {key} for {instance} on the VM: "
                           "run the beforeAll hook or `python3 isolation.py snapshot`")
    _cycle(run, ["docker", "run", "--rm", *_mounts(""), "-v", f"{SNAPSHOT_ROOT}:/s:ro", _image(),
                 "sh", "-c", RESTORE_SH, "restore", instance, key], "putting the volumes back")
    wait_healthy(run, timeout, clock, sleep)
    return clock() - start
