"""isolation.py against a fake VM and recorded API answers. No VM, no model."""
import json
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

import isolation
from handoff import ConfigError

STAMP, KEY = "2026-10-22T12:34:56Z", "2026-10-22T123456Z"
EXISTS = f"/s/eval-01/{KEY}/COMPLETE"
ROLES = Path(__file__).resolve().parents[2] / "ansible" / "roles"


def cp(code=0, out="", err=""):
    return subprocess.CompletedProcess([], code, out, err)


HEALTHY = "".join(f"/{c} running none\n" for c in isolation.CONTAINERS)
DIRS = {"workflow-stack": "/home/ubuntu/workflow-stack", "spe-frontend": "/home/ubuntu/spe-frontend"}


def _project(c):
    return "spe-frontend" if c == isolation.SANDBOX else "workflow-stack"


LABELS = "".join(f"/{c}|{_project(c)}|{DIRS[_project(c)]}|{DIRS[_project(c)]}/docker-compose.yml|"
                 f"{c.removeprefix(_project(c) + '-').removesuffix('-1')}\n" for c in isolation.CONTAINERS)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeVM:
    """Answers by the first rule whose marker occurs in the joined argv; records every call."""

    def __init__(self, **over):
        self.calls = []
        self.rules = {"volume inspect": cp(), EXISTS: cp(), "com.docker.compose": cp(out=LABELS),
                      "docker stop": cp(), "docker run": cp(), "--force-recreate": cp(),
                      "docker inspect": cp(out=HEALTHY), "service-info": cp(out="200 200 200 ")}
        self.rules.update(over)

    def __call__(self, argv, stdin=None):
        self.calls.append(list(argv))
        joined = " ".join(argv)
        for marker, out in self.rules.items():
            if marker in joined:
                return out(argv, stdin) if callable(out) else out
        raise AssertionError(f"unexpected command: {joined}")

    def index(self, marker):
        return next(i for i, a in enumerate(self.calls) if marker in " ".join(a))

    def count(self, marker):
        return sum(marker in " ".join(a) for a in self.calls)


@pytest.fixture
def hdir(tmp_path):
    (tmp_path / "canaries.json").write_text(json.dumps(
        {"instance": "eval-01", "seed": 1, "api_host": "h", "generated_at": STAMP, "study_ids": [], "tokens": []}))
    return tmp_path


def test_snapshot_key_follows_the_build(hdir):
    assert isolation.snapshot_key(hdir) == ("eval-01", KEY)


@pytest.mark.parametrize("record", [{"instance": "a;rm -rf /", "generated_at": STAMP},
                                    {"instance": "eval-01", "generated_at": "yesterday"}, None])
def test_bad_or_missing_record_is_a_config_error(tmp_path, record):
    if record is not None:
        (tmp_path / "canaries.json").write_text(json.dumps(record))
    with pytest.raises(ConfigError):
        isolation.snapshot_key(tmp_path)


def test_restore_stops_untars_recreates_then_waits(hdir):
    clock = Clock()

    def untar(argv, stdin):
        clock.t += 40
        return cp()

    vm = FakeVM(**{"docker run": untar})
    assert isolation.restore(hdir, run=vm, clock=clock, sleep=clock.sleep) == 40.0
    order = [vm.index(m) for m in ("volume inspect", EXISTS, "com.docker.compose", "docker stop", "/v/*",
                                   "--force-recreate", "State.Status", "service-info")]
    assert order == sorted(order)
    untar_call = vm.calls[vm.index("/v/*")]
    for vol in isolation.VOLUMES:
        assert f"{vol}:/v/{vol}" in untar_call
    assert f"{isolation.SNAPSHOT_ROOT}:/s:ro" in untar_call and untar_call[-2:] == ["eval-01", KEY]


def test_restore_refuses_without_snapshot_of_this_build(hdir):
    vm = FakeVM(**{EXISTS: cp(1)})
    with pytest.raises(isolation.RestoreError, match="no complete snapshot"):
        isolation.restore(hdir, run=vm)
    assert vm.count("docker stop") == 0


def test_restore_fails_loudly_on_a_missing_volume(hdir):
    vm = FakeVM(**{"volume inspect": cp(1, err="Error: No such volume: workflow-stack_trs-mongodb")})
    with pytest.raises(isolation.RestoreError, match="trs-mongodb"):
        isolation.restore(hdir, run=vm)
    assert vm.count("docker stop") == 0


def test_restore_raises_when_stack_stays_unhealthy(hdir):
    clock = Clock()
    vm = FakeVM(**{"docker inspect": cp(out=HEALTHY.replace("rest-1 running", "rest-1 exited"))})
    with pytest.raises(isolation.RestoreError, match="not healthy.*rest-1"):
        isolation.restore(hdir, run=vm, timeout=10, clock=clock, sleep=clock.sleep)
    assert vm.count("--force-recreate") == 2


def test_restore_recreates_every_container_from_its_project(hdir):
    vm = FakeVM()
    isolation.restore(hdir, run=vm)
    ups = [c for c in vm.calls if "--force-recreate" in c]
    assert vm.count("docker start") == 0 and len(ups) == 2
    recreated = set()
    for up in ups:
        project = up[up.index("-p") + 1]
        assert up[:2] == ["docker", "compose"] and up[up.index("--project-directory") + 1] == DIRS[project]
        assert up[up.index("-f") + 1] == f"{DIRS[project]}/docker-compose.yml"
        assert {"--renew-anon-volumes", "--no-deps", "--no-build"} <= set(up)
        recreated |= {f"{project}-{s}-1" for s in up[up.index("--pull") + 2:]}
    assert recreated == set(isolation.CONTAINERS)  # the agent and traefik are never among them


def test_restore_refuses_a_container_without_compose_labels(hdir):
    vm = FakeVM(**{"com.docker.compose": cp(out=LABELS.replace("|spe-frontend|", "|||"))})
    with pytest.raises(isolation.RestoreError, match="sandbox-1: no Compose labels"):
        isolation.restore(hdir, run=vm)
    assert vm.count("docker stop") == 0


def test_restore_raises_when_apis_do_not_answer(hdir):
    clock = Clock()
    vm = FakeVM(**{"service-info": cp(out="200 502 200 ")})
    with pytest.raises(isolation.RestoreError, match="502"):
        isolation.restore(hdir, run=vm, timeout=10, clock=clock, sleep=clock.sleep)


def test_restore_starts_the_stack_even_when_untar_fails(hdir):
    vm = FakeVM(**{"docker run": cp(1, err="tar: short read")})
    with pytest.raises(isolation.RestoreError, match="putting the volumes back"):
        isolation.restore(hdir, run=vm)
    assert vm.count("--force-recreate") == 2


def test_unreachable_vm_fails_at_once(hdir):
    vm = FakeVM(**{"docker inspect": cp(255, err="ssh: connect to host vm: Connection refused")})
    with pytest.raises(isolation.RestoreError, match="unreachable"):
        isolation.restore(hdir, run=vm)
    assert vm.count("State.Status") == 1


def test_snapshot_saves_every_volume_and_marks_complete(hdir):
    vm = FakeVM()
    isolation.snapshot(hdir, run=vm)
    call = vm.calls[vm.index("tar -cf")]
    for vol in isolation.VOLUMES:
        assert f"{vol}:/v/{vol}:ro" in call
    assert f"{isolation.SNAPSHOT_ROOT}:/s" in call and call[-2:] == ["eval-01", KEY]
    assert 'rm -rf "/s/$1"' in call[-4] and "COMPLETE" in call[-4]
    assert vm.index("docker stop") < vm.index("tar -cf") < vm.index("--force-recreate") < vm.index("service-info")


@pytest.mark.parametrize("code,expected", [(0, True), (1, False), (125, None)])
def test_snapshot_exists_reads_the_complete_marker(hdir, code, expected):
    vm = FakeVM(**{EXISTS: cp(code, err="docker: error")})
    if expected is None:
        with pytest.raises(isolation.RestoreError):
            isolation.snapshot_exists(hdir, run=vm)
    else:
        assert isolation.snapshot_exists(hdir, run=vm) is expected


def test_vm_runner_quotes_for_ssh(hdir, monkeypatch):
    seen = []
    monkeypatch.setattr(isolation, "vm_argv", lambda d: ["ssh", "-F", "cfg", "ubuntu@vm"])
    monkeypatch.setattr(isolation.subprocess, "run", lambda argv, **kw: seen.append((argv, kw)) or cp())
    isolation.vm_runner(hdir)(["sh", "-c", "a b; c"], "stdin")
    assert seen[0][0] == ["ssh", *isolation.SSH_MUX, "-F", "cfg", "ubuntu@vm", "sh -c 'a b; c'"]
    assert seen[0][1]["input"] == "stdin"
    monkeypatch.setattr(isolation, "vm_argv", lambda d: [])
    isolation.vm_runner(hdir)(["docker", "ps"])
    assert seen[1][0] == ["docker", "ps"]


def _compose(path):
    # The workflow stack's file is a Jinja template; the frontend's is plain Compose with ${VAR}s, which YAML reads as is.
    data = yaml.safe_load(re.sub(r"\{\{.*?\}\}", "x", path.read_text()))
    return data["name"], set(data.get("volumes") or {}), set(data["services"])


def test_volumes_match_the_compose_files():
    declared, services = set(), set()
    for tpl in (ROLES / "workflow_stack/templates/compose.install.yaml.j2",
                ROLES.parents[1] / "instance/compose.yml"):
        project, vols, svcs = _compose(tpl)
        declared |= {f"{project}_{v}" for v in vols}
        services |= {f"{project}-{s}-1" for s in svcs}
    assert set(isolation.VOLUMES) | set(isolation.NOT_RESTORED) == declared
    assert not set(isolation.VOLUMES) & set(isolation.NOT_RESTORED)
    assert set(isolation.CONTAINERS) <= services and isolation.SANDBOX in isolation.CONTAINERS
