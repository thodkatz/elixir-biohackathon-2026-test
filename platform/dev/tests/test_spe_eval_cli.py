"""The `spe-eval` command line (experiments spec part 03, decisions 7, 9, 11, 18, 22; part 07's
command table): `arm`, `run` (with `--detach`), `status`, `wait`, `runs`, `new` and `test`. Fakes
`spe-apply`, `run.sh` and `systemd-run` so no real Ansible, Docker or model call happens; a tiny
two-experiment catalogue (`one-arm`, `two-arm`) keeps each test fast and independent of the real
`experiments/`/`mitigations/` files (those are exercised against the real catalogue by
`test_spe_eval.py`).

The health wait (task 4 review, Critical 1) probes a real `http.server` on `127.0.0.1`, not a
fake `spe-apply status` line: the real script prints the `/healthz` response *body*
(`{"status": "ok", ...}`), not a bare status code, so a fake that invented `agent /healthz: 200`
was asserting a contract the real script does not have.

`new` and `test` (slice 6, task 2) get their own fixture, `new_repo`: a writable copy of the real
catalog *and* enough code (`validate.py`, `check_experiment.py` and its own dependencies) for
`check_experiment.py` to run from inside it exactly as it would in a real workspace -- its own
catalogue label checks (`group`, `threat`, `path`, `closed_by`) always read its own script's
location, so a synthetic new test file is only visible to a `check_experiment.py` run from the
same copy, never to the real repo's module imported directly (see `copy_catalog`).
"""
import http.server
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parents[2]  # platform/dev/tests -> platform
REPO = HERE.parent
SPE_EVAL = HERE / "instance" / "spe-eval"

FAKE_SPE_APPLY = """#!/bin/sh
echo "$*" >> "$FAKE_SPE_APPLY_LOG"
exit "${FAKE_SPE_APPLY_EXIT:-0}"
"""

# Mirrors run.sh's own --reports-dir contract (gate-notes.json always written, run.json only on
# success: experiments spec 03), without any real promptfoo/model call.
FAKE_RUN_SH = """#!/bin/sh
echo "$*" >> "$FAKE_RUN_SH_LOG"
shift 2
reports_dir=""
while [ $# -gt 0 ]; do
  case "$1" in
    --suite) shift 2 ;;
    --reports-dir) reports_dir=$2; shift 2 ;;
    --description) shift 2 ;;
    *) shift ;;
  esac
done
if [ -n "${FAKE_RUN_SH_SLEEP:-}" ]; then sleep "$FAKE_RUN_SH_SLEEP"; fi
code=${FAKE_RUN_SH_EXIT:-0}
if [ -n "$reports_dir" ]; then
  mkdir -p "$reports_dir"
  echo '{"results": {"results": []}}' > "$reports_dir/controls.json"
  echo '{"results": {"results": []}}' > "$reports_dir/agent.json"
  echo '[]' > "$reports_dir/gate-notes.json"
  if [ "$code" = 0 ]; then
    echo '{"started": "2026-11-10T12:00:00Z", "canaries_sha256": "abc"}' > "$reports_dir/run.json"
  fi
fi
exit "$code"
"""

# Starts, in the background, logs its call and returns at once (as the real systemd-run does:
# task 4 review, Important 3 needs the *child* to take the lock asynchronously so --detach's own
# poll loop has something real to wait for). Unless FAKE_SYSTEMD_RUN_NO_ACQUIRE is set, the
# background subshell takes the lock file's flock itself (mirroring spe_eval.Lock's own format:
# the token alone, written once the flock succeeds) and holds it for FAKE_SYSTEMD_RUN_HOLD
# seconds, simulating the detached `spe-eval run` child actually running.
FAKE_SYSTEMD_RUN = """#!/bin/sh
echo "$*" >> "$FAKE_SYSTEMD_RUN_LOG"
if [ -n "${FAKE_SYSTEMD_RUN_ENV_LOG:-}" ]; then
  echo "XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-}" >> "$FAKE_SYSTEMD_RUN_ENV_LOG"
  echo "DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-}" >> "$FAKE_SYSTEMD_RUN_ENV_LOG"
fi
if [ -n "${FAKE_SYSTEMD_RUN_NO_ACQUIRE:-}" ]; then exit 0; fi
token=""
for a in "$@"; do
  case "$a" in
    --setenv=SPE_EVAL_RUN_ID=*) token=${a#--setenv=SPE_EVAL_RUN_ID=} ;;
  esac
done
lock_file="$HOME/spe-eval/lock"
mkdir -p "$(dirname "$lock_file")"
# Detached from this script's own stdin/stdout/stderr (as the real systemd-run also would, and
# unlike an inline "&" background job): otherwise, since those are `subprocess.run(capture_output=
# True)`'s own pipes, the backgrounded subshell inheriting them keeps the write end open for its
# whole FAKE_SYSTEMD_RUN_HOLD, so the *caller's* subprocess.run does not return until the hold is
# already over -- by which time a holder() that checks the real flock (task 5 review, Important
# 4a) correctly finds it already released, instead of "still running".
(
  exec 9>"$lock_file"
  flock 9
  printf '%s' "$token" >&9
  sleep "${FAKE_SYSTEMD_RUN_HOLD:-0.5}"
) >/dev/null 2>&1 </dev/null &
exit 0
"""


class _HealthServer:
    """A real HTTP server answering `/healthz` on `127.0.0.1`, for `_wait_for_stack`'s direct
    probe. `status_code`/`body` mirror what the real agent's `/healthz` sends (200
    `{"status": "ok", ...}` when ready, 503 `{"status": "starting", ...}` otherwise)."""

    def __init__(self, status_code: int = 200, body: bytes = b'{"status": "ok", "tools": 1}'):
        status, payload = status_code, body

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler's own naming)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):  # keep test output clean
                pass

        self._httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._httpd.server_port}/healthz"

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def setup(tmp_path):
    repo = tmp_path / "repo"
    (repo / "experiments").mkdir(parents=True)
    (repo / "mitigations").mkdir(parents=True)
    (repo / "platform" / "ansible" / "instances").mkdir(parents=True)
    (repo / "platform" / "ansible" / "catalog" / "injections").mkdir(parents=True)
    (repo / "platform" / "promptfoo-evals").mkdir(parents=True)

    (repo / "platform" / "ansible" / "catalog" / "injections" / "fixtures.json").write_text(
        json.dumps({"fixtures": []}))

    common_params = {"samples": ["HG002"], "tiers": ["ref"], "workflows": ["wk1"], "smoke_test": False}
    (repo / "experiments" / "one-arm.yml").write_text(yaml.safe_dump({
        "parameters": {"experiment": "one-arm", "mitigations": [], **common_params},
        "experiment": {"mitigation": None, "base": [], "injections": [], "tests": []},
        "vars": {},
    }))
    (repo / "experiments" / "two-arm.yml").write_text(yaml.safe_dump({
        "parameters": {"experiment": "two-arm", "mitigations": [], **common_params},
        "experiment": {"mitigation": "M1", "base": [], "injections": [], "tests": []},
        "vars": {},
    }))
    (repo / "mitigations" / "M1.yml").write_text(yaml.safe_dump({
        "id": "M1", "on": {"spe_test_switch": True}, "off": {"spe_test_switch": False}, "probes": [],
    }))
    (repo / "platform" / "ansible" / "instances" / "local.yml").write_text(yaml.safe_dump({
        "spe_experiment": "one-arm", "spe_mitigations": [],
        "spe_samples": ["HG002"], "spe_tiers": ["ref"], "spe_workflows": ["wk1"], "spe_run_smoke_test": False,
        "spe_agent_model_provider": "anthropic", "spe_agent_model": "claude-haiku-5-5",
    }))
    (repo / "platform" / "promptfoo-evals" / "agent.yaml").write_text("tests: []\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, content in (("spe-apply", FAKE_SPE_APPLY), ("systemd-run", FAKE_SYSTEMD_RUN)):
        path = bin_dir / name
        path.write_text(content)
        path.chmod(0o755)
    run_sh = repo / "platform" / "promptfoo-evals" / "run.sh"
    run_sh.write_text(FAKE_RUN_SH)
    run_sh.chmod(0o755)

    home = tmp_path / "home"
    home.mkdir()
    log_apply = tmp_path / "spe-apply.log"
    log_run_sh = tmp_path / "run-sh.log"
    log_systemd = tmp_path / "systemd-run.log"
    health = _HealthServer(200)  # the default: every arm's apply is answered at once

    def base_env(env):
        return {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(home),
                "SPE_REPO_DIR": str(repo), "FAKE_SPE_APPLY_LOG": str(log_apply),
                "FAKE_RUN_SH_LOG": str(log_run_sh), "FAKE_SYSTEMD_RUN_LOG": str(log_systemd),
                "SPE_EVAL_HEALTH_URL": health.url, "SPE_EVAL_HEALTH_INTERVAL": "0.01",
                "SPE_EVAL_HEALTH_TIMEOUT": "0.3", "SPE_EVAL_WAIT_INTERVAL": "0.05",
                "SPE_EVAL_DETACH_WAIT_TIMEOUT": "3", "SPE_EVAL_DETACH_WAIT_INTERVAL": "0.02",
                **(env or {})}

    def run(*args, env=None, timeout=20):
        return subprocess.run([sys.executable, str(SPE_EVAL), *args], env=base_env(env), capture_output=True,
                               text=True, timeout=timeout)

    def popen(*args, env=None):
        return subprocess.Popen([sys.executable, str(SPE_EVAL), *args], env=base_env(env),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def calls(log_path: Path) -> list[str]:
        return log_path.read_text().splitlines() if log_path.exists() else []

    try:
        yield run, popen, calls, repo, home, {"apply": log_apply, "run_sh": log_run_sh, "systemd": log_systemd}
    finally:
        health.close()


def wait_until_locked(home: Path, timeout: float = 5.0) -> None:
    lock = home / "spe-eval" / "lock"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if lock.exists() and lock.read_text().strip():
            return
        time.sleep(0.02)
    raise AssertionError("lock never appeared")


# --- arm ---------------------------------------------------------------------------------------

def test_arm_one_arm_experiment_applies_and_waits(setup):
    run, _popen, calls, _repo, _home, logs = setup
    p = run("arm", "one-arm", "baseline")
    assert p.returncode == 0, p.stderr
    assert "applied" in p.stdout
    apply_calls = calls(logs["apply"])
    assert any(c.startswith("all -e @") for c in apply_calls)


def test_arm_exits_1_when_the_stack_never_answers(setup):
    # task 4 review, Critical 1: a real (never-ready) health server, not a fake spe-apply line.
    run, _popen, _calls, _repo, _home, _logs = setup
    unhealthy = _HealthServer(503, b'{"status": "starting", "reason": "still loading"}')
    try:
        p = run("arm", "one-arm", "baseline", env={"SPE_EVAL_HEALTH_URL": unhealthy.url})
        assert p.returncode == 1, p.stdout
        assert "did not answer in time" in p.stderr
    finally:
        unhealthy.close()


def test_arm_unknown_arm_name_is_a_configuration_error(setup):
    # one-arm has baseline only: "mitigated" raises ValueError (arm_mitigations), mapped to exit 2
    # by main() (task 3 review, minor 2).
    run, _popen, _calls, _repo, _home, _logs = setup
    p = run("arm", "one-arm", "mitigated")
    assert p.returncode == 2, p.stdout
    assert "not an arm" in p.stderr


def test_arm_refuses_while_locked(setup):
    run, popen, _calls, _repo, home, _logs = setup
    holder = popen("run", "one-arm", env={"FAKE_RUN_SH_SLEEP": "1"})
    try:
        wait_until_locked(home)
        p = run("arm", "one-arm", "baseline")
        assert p.returncode == 2, p.stdout
        assert "holds the lock" in p.stderr
    finally:
        holder.communicate(timeout=10)


# --- run ---------------------------------------------------------------------------------------

def test_run_json_keeps_canaries_sha256_from_run_sh(setup):
    # task 5 review, Important 3: spe-eval's own run.json write (state/ended/gate_notes), in
    # cmd_run's `finally`, must merge into the run.json run.sh already wrote on success rather
    # than overwrite it outright, or matrix.counts/replay.py never find canaries_sha256 again.
    run, _popen, _calls, _repo, home, _logs = setup
    p = run("run", "one-arm", env={"SPE_EVAL_RUN_ID": "20261110T190000Z"})
    assert p.returncode == 0, p.stderr
    record = json.loads((home / "spe-eval" / "reports" / "one-arm" / "20261110T190000Z" / "baseline" /
                          "run.json").read_text())
    assert record["canaries_sha256"] == "abc"  # FAKE_RUN_SH's own run.json, on success
    assert record["started"]
    assert record["state"] == "ok"


def test_run_two_arm_order_and_return_to_build_arm(setup):
    run, _popen, calls, _repo, home, logs = setup
    p = run("run", "two-arm", env={"SPE_EVAL_RUN_ID": "20261110T100000Z"})
    assert p.returncode == 0, p.stderr

    apply_calls = [c for c in calls(logs["apply"]) if c.startswith("all")]
    # baseline applied, mitigated applied, then the build's own arm reapplied with no override.
    assert len(apply_calls) == 3
    assert apply_calls[0].startswith("all -e @")
    assert apply_calls[1].startswith("all -e @")
    assert apply_calls[2] == "all"

    for arm in ("baseline", "mitigated"):
        record = json.loads((home / "spe-eval" / "reports" / "two-arm" / "20261110T100000Z" / arm /
                              "run.json").read_text())
        assert record["state"] == "ok"
        assert record["experiment"] == "two-arm"
        assert record["run"] == "20261110T100000Z"
    baseline = json.loads((home / "spe-eval" / "reports" / "two-arm" / "20261110T100000Z" / "baseline" /
                            "run.json").read_text())
    mitigated = json.loads((home / "spe-eval" / "reports" / "two-arm" / "20261110T100000Z" / "mitigated" /
                             "run.json").read_text())
    assert baseline["mitigations"] == []
    assert mitigated["mitigations"] == ["M1"]

    # An opening line when the run starts (end null), so a hit during a long run is already in a window,
    # then the closing line at its end, with the same start.
    windows = [json.loads(line) for line in (home / "spe-eval" / "windows.jsonl").read_text().splitlines()]
    assert len(windows) == 2
    opening, closing = windows
    assert opening == {"run": "20261110T100000Z", "experiment": "two-arm", "start": closing["start"], "end": None}
    assert closing["run"] == "20261110T100000Z" and closing["experiment"] == "two-arm"
    assert closing["end"] and closing["start"] <= closing["end"]


def test_run_gate_refused_is_recorded_and_exits_1(setup):
    run, _popen, _calls, _repo, home, _logs = setup
    p = run("run", "one-arm", env={"SPE_EVAL_RUN_ID": "20261110T110000Z", "FAKE_RUN_SH_EXIT": "3"})
    assert p.returncode == 1, p.stdout
    record = json.loads((home / "spe-eval" / "reports" / "one-arm" / "20261110T110000Z" / "baseline" /
                          "run.json").read_text())
    assert record["state"] == "gate refused"


def test_run_existing_reports_dir_is_refused(setup):
    run, _popen, _calls, _repo, home, _logs = setup
    existing = home / "spe-eval" / "reports" / "one-arm" / "20261110T120000Z" / "baseline"
    existing.mkdir(parents=True)
    p = run("run", "one-arm", env={"SPE_EVAL_RUN_ID": "20261110T120000Z"})
    assert p.returncode == 2, p.stdout
    assert "already exists" in p.stderr


@pytest.mark.parametrize("repeat", ["0", "-1", "x"])
def test_run_bad_repeat_is_rejected_up_front(setup, repeat):
    # task 5 review, Minor: run.sh's own usage check only runs after a full `spe-apply all`,
    # marking the arm `failed`; argparse must catch a bad --repeat before any of that.
    run, _popen, calls, _repo, _home, logs = setup
    p = run("run", "one-arm", "--repeat", repeat)
    assert p.returncode == 2, p.stdout
    assert calls(logs["apply"]) == []


def test_run_refuses_while_another_run_holds_the_lock(setup):
    run, popen, _calls, _repo, home, _logs = setup
    holder = popen("run", "one-arm", env={"FAKE_RUN_SH_SLEEP": "1", "SPE_EVAL_RUN_ID": "20261110T130000Z"})
    try:
        wait_until_locked(home)
        p = run("run", "one-arm")
        assert p.returncode == 2, p.stdout
        assert "20261110T130000Z holds the lock" in p.stderr
    finally:
        holder.communicate(timeout=10)


def test_run_sigterm_mid_run_sh_marks_stopped_and_still_cleans_up(setup):
    # task 4 review, Important 2: a stop mid-run.sh still writes a terminal run.json, the
    # windows.jsonl line, and still returns to the build's own arm, all before the lock frees.
    run, popen, calls, _repo, home, logs = setup
    proc = popen("run", "one-arm", env={"SPE_EVAL_RUN_ID": "20261111T100000Z", "FAKE_RUN_SH_SLEEP": "2"})
    try:
        wait_until_locked(home)
        time.sleep(0.3)  # let the fake apply/health-wait finish and run.sh actually start sleeping
        proc.send_signal(signal.SIGTERM)
        _out, err = proc.communicate(timeout=10)
        assert proc.returncode == 1, err
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=5)

    record = json.loads((home / "spe-eval" / "reports" / "one-arm" / "20261111T100000Z" / "baseline" /
                          "run.json").read_text())
    assert record["state"] == "stopped"
    assert record["ended"]

    windows = [json.loads(line) for line in (home / "spe-eval" / "windows.jsonl").read_text().splitlines()]
    assert [(w["run"], w["end"] is None) for w in windows] == [("20261111T100000Z", True),
                                                                ("20261111T100000Z", False)]

    apply_calls = [c for c in calls(logs["apply"]) if c.startswith("all")]
    assert apply_calls[-1] == "all"  # the return-to-build-arm reapply still ran


def test_run_detach_prints_the_run_id_and_returns_at_once(setup):
    run, _popen, calls, _repo, _home, logs = setup
    started = time.monotonic()
    p = run("run", "one-arm", "--detach", env={"FAKE_SYSTEMD_RUN_HOLD": "2"})
    elapsed = time.monotonic() - started
    assert p.returncode == 0, p.stderr
    run_id = p.stdout.strip().splitlines()[-1]
    assert re.fullmatch(r"\d{8}T\d{6}Z", run_id)
    assert elapsed < 5
    systemd_calls = calls(logs["systemd"])
    assert len(systemd_calls) == 1
    assert f"--unit=spe-eval-{run_id}" in systemd_calls[0]
    assert f"SPE_EVAL_RUN_ID={run_id}" in systemd_calls[0]
    assert "run one-arm --repeat 1" in systemd_calls[0]


def test_run_detach_validates_before_starting_the_unit(setup):
    # task 4 review, Important 3: a typo'd experiment never reaches systemd-run.
    run, _popen, calls, _repo, _home, logs = setup
    p = run("run", "no-such-experiment", "--detach")
    assert p.returncode == 2, p.stdout
    assert calls(logs["systemd"]) == []


def test_run_detach_refuses_while_locked(setup):
    run, popen, calls, _repo, home, logs = setup
    holder = popen("run", "one-arm", env={"FAKE_RUN_SH_SLEEP": "1", "SPE_EVAL_RUN_ID": "20261111T110000Z"})
    try:
        wait_until_locked(home)
        p = run("run", "one-arm", "--detach")
        assert p.returncode == 2, p.stdout
        assert "holds the lock" in p.stderr
        assert calls(logs["systemd"]) == []
    finally:
        holder.communicate(timeout=10)


def test_run_detach_waits_for_the_child_to_hold_the_lock(setup):
    # task 4 review, Important 3: --detach does not return until the (simulated) child has
    # actually taken the lock, so a `wait` right after sees a run in progress, not "no run".
    run, _popen, _calls, _repo, home, _logs = setup
    p = run("run", "one-arm", "--detach", env={"FAKE_SYSTEMD_RUN_HOLD": "2"})
    assert p.returncode == 0, p.stderr
    run_id = p.stdout.strip().splitlines()[-1]
    lock = home / "spe-eval" / "lock"
    assert lock.read_text().strip() == run_id


def test_run_detach_exits_1_if_the_child_never_takes_the_lock(setup):
    run, _popen, _calls, _repo, _home, _logs = setup
    p = run("run", "one-arm", "--detach", env={"FAKE_SYSTEMD_RUN_NO_ACQUIRE": "1",
                                                "SPE_EVAL_DETACH_WAIT_TIMEOUT": "0.2"})
    assert p.returncode == 1, p.stdout
    assert "did not take the lock" in p.stderr


def test_run_detach_defaults_the_user_bus_when_unset(setup, tmp_path):
    # task 5 review, Important 4b: the Coder agent is a system unit with no PAM session, so its
    # shells have neither XDG_RUNTIME_DIR nor DBUS_SESSION_BUS_ADDRESS; systemd-run --user then
    # fails to connect to the bus. spe-eval must default both, from /run/user/<uid>, rather than
    # pass them through unset.
    run, _popen, _calls, _repo, _home, logs = setup
    env_log = tmp_path / "systemd-env.log"
    p = run("run", "one-arm", "--detach",
            env={"FAKE_SYSTEMD_RUN_ENV_LOG": str(env_log), "XDG_RUNTIME_DIR": "", "DBUS_SESSION_BUS_ADDRESS": ""})
    assert p.returncode == 0, p.stderr
    lines = env_log.read_text().splitlines()
    uid = os.getuid()
    assert lines == [f"XDG_RUNTIME_DIR=/run/user/{uid}",
                     f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus"]


def test_run_detach_keeps_an_already_set_user_bus(setup, tmp_path):
    run, _popen, _calls, _repo, _home, logs = setup
    env_log = tmp_path / "systemd-env.log"
    p = run("run", "one-arm", "--detach",
            env={"FAKE_SYSTEMD_RUN_ENV_LOG": str(env_log), "XDG_RUNTIME_DIR": "/custom/run",
                 "DBUS_SESSION_BUS_ADDRESS": "unix:path=/custom/run/bus"})
    assert p.returncode == 0, p.stderr
    assert env_log.read_text().splitlines() == ["XDG_RUNTIME_DIR=/custom/run",
                                                "DBUS_SESSION_BUS_ADDRESS=unix:path=/custom/run/bus"]


# --- status / wait / runs ----------------------------------------------------------------------

def test_status_json_reports_the_run_in_progress(setup):
    run, popen, _calls, _repo, home, _logs = setup
    holder = popen("run", "one-arm", env={"FAKE_RUN_SH_SLEEP": "1", "SPE_EVAL_RUN_ID": "20261110T140000Z"})
    try:
        wait_until_locked(home)
        p = run("status", "--json")
        assert p.returncode == 0, p.stderr
        info = json.loads(p.stdout)
        assert info["locked"] is True
        assert info["holder"] == "20261110T140000Z"
        assert info["run"] == "20261110T140000Z"
        assert info["experiment"] == "one-arm"
        assert info["arm"] == "baseline"
        assert info["state"] == "running"
    finally:
        holder.communicate(timeout=10)


def test_status_json_with_no_run_yet(setup):
    run, _popen, _calls, _repo, _home, _logs = setup
    p = run("status", "--json")
    assert p.returncode == 0, p.stderr
    info = json.loads(p.stdout)
    assert info == {"locked": False, "holder": None, "run": None, "experiment": None, "arm": None,
                     "state": None, "done": None, "total": None, "last_error": None}


def test_status_while_held_by_arm_leaves_run_arm_state_null(setup):
    # task 4 review, minor 6: a holder with no report of its own (here, `arm`) must not be shown
    # next to some earlier run's details.
    run, popen, _calls, _repo, home, _logs = setup
    prior = run("run", "one-arm", env={"SPE_EVAL_RUN_ID": "20261111T120000Z"})
    assert prior.returncode == 0, prior.stderr

    unhealthy = _HealthServer(503, b'{"status": "starting"}')
    try:
        # A generous health timeout (well past another subprocess's startup time under load),
        # so the lock is reliably still held when `status` is checked below.
        holder = popen("arm", "one-arm", "baseline",
                        env={"SPE_EVAL_HEALTH_URL": unhealthy.url, "SPE_EVAL_HEALTH_TIMEOUT": "5"})
        try:
            wait_until_locked(home)
            p = run("status", "--json")
            assert p.returncode == 0, p.stderr
            info = json.loads(p.stdout)
            assert info["locked"] is True
            assert info["run"] is None
            assert info["arm"] is None
            assert info["state"] is None
        finally:
            holder.communicate(timeout=10)
    finally:
        unhealthy.close()


def test_wait_timeout_exits_1_and_says_so(setup):
    run, popen, _calls, _repo, home, _logs = setup
    holder = popen("run", "one-arm", env={"FAKE_RUN_SH_SLEEP": "2", "SPE_EVAL_RUN_ID": "20261110T150000Z"})
    try:
        wait_until_locked(home)
        started = time.monotonic()
        p = run("wait", "--timeout", "0.2")
        elapsed = time.monotonic() - started
        assert p.returncode == 1, p.stdout
        assert "did not finish within" in p.stderr
        assert elapsed < 2
    finally:
        holder.communicate(timeout=10)


def test_wait_returns_the_run_s_outcome_once_the_lock_frees(setup):
    run, popen, _calls, _repo, home, _logs = setup
    holder = popen("run", "one-arm", env={"FAKE_RUN_SH_SLEEP": "0.3", "SPE_EVAL_RUN_ID": "20261110T160000Z"})
    try:
        wait_until_locked(home)
        p = run("wait", "--timeout", "5")
        assert p.returncode == 0, p.stdout
        assert "baseline: ok" in p.stdout
    finally:
        holder.communicate(timeout=10)


def test_wait_with_no_run_at_all(setup):
    run, _popen, _calls, _repo, _home, _logs = setup
    p = run("wait")
    assert p.returncode == 0, p.stderr
    assert "no run has happened yet" in p.stdout


def test_wait_when_lock_already_free_judges_the_newest_run(setup):
    # task 4 review, Important 3: wait must not exit 0 unconditionally just because the lock
    # happens to be free when it is called -- `run --detach && wait` racing past the run's own
    # end must still see that run's real outcome.
    run, _popen, _calls, _repo, _home, _logs = setup
    first = run("run", "one-arm", env={"SPE_EVAL_RUN_ID": "20261111T130000Z", "FAKE_RUN_SH_EXIT": "3"})
    assert first.returncode == 1, first.stderr
    p = run("wait")
    assert p.returncode == 1, p.stdout
    assert "baseline: gate refused" in p.stdout


def test_wait_for_an_arm_holder_with_no_report_exits_0(setup):
    # task 4 review, minor 7: no report is not evidence of a failed *run* when the holder was an
    # `arm` (which keeps none by design). A never-ready health server keeps the lock held for
    # SPE_EVAL_HEALTH_TIMEOUT so `wait` reliably calls in while it is still held.
    #
    # Whole-branch review, the flaky test: the fixture's default 0.3s timeout raced `wait`'s own
    # process start (a fresh Python interpreter importing yaml/validate/injections_schema before
    # it ever calls holder()), which under CPU load can take longer than 0.3s -- `wait` would then
    # find the lock already free and report "no run has happened yet" instead. Give the holder a
    # long hold (~4s, well past that startup cost even under load) and `wait` a bounded timeout
    # above it (10s), so the real race is between "wait sees the run in progress" and a generous
    # deadline, not between two near-equal durations.
    run, popen, _calls, _repo, home, _logs = setup
    unhealthy = _HealthServer(503, b'{"status": "starting"}')
    try:
        holder = popen("arm", "one-arm", "baseline",
                       env={"SPE_EVAL_HEALTH_URL": unhealthy.url, "SPE_EVAL_HEALTH_TIMEOUT": "4"})
        try:
            wait_until_locked(home)
            p = run("wait", "--timeout", "10")
            assert p.returncode == 0, p.stdout
            assert "no report found" in p.stdout
        finally:
            holder.communicate(timeout=10)
    finally:
        unhealthy.close()


def test_runs_ordering_and_json_fields(setup):
    run, _popen, _calls, _repo, _home, _logs = setup
    first = run("run", "one-arm", env={"SPE_EVAL_RUN_ID": "20261110T170000Z"})
    assert first.returncode == 0, first.stderr
    second = run("run", "one-arm", env={"SPE_EVAL_RUN_ID": "20261110T180000Z"})
    assert second.returncode == 0, second.stderr

    p = run("runs", "--json")
    assert p.returncode == 0, p.stderr
    entries = json.loads(p.stdout)
    assert [e["run"] for e in entries] == ["20261110T180000Z", "20261110T170000Z"]  # newest first
    assert entries[0]["experiment"] == "one-arm"
    assert entries[0]["arms"]["baseline"]["state"] == "ok"
    assert entries[0]["arms"]["baseline"]["model"] == "anthropic:claude-haiku-5-5"  # decision 22


def test_runs_text_output_with_none_yet(setup):
    run, _popen, _calls, _repo, _home, _logs = setup
    p = run("runs")
    assert p.returncode == 0, p.stderr
    assert "none yet" in p.stdout


# ---------------------------------------------------------------------------
# new (07-agent-friendly.md, *Start*; 05-contribution.md, *A skeleton*)
# ---------------------------------------------------------------------------

def copy_catalog(tmp_path: Path) -> Path:
    """A writable copy of the whole real repo's catalog, and enough of its code, for `spe-eval
    new` to read and write and for `check_experiment.py` to run over the result exactly as it
    would in a real workspace: `threats/`, `paths/`, `mitigations/`, `experiments/`,
    `validate.py` and `check_experiment.py` themselves (at the copy's own root, so its label
    checks -- `group`, `threat`, `path`, `closed_by` -- see the copy's own new files, not the real
    repo's: check_experiment.py's own `PROMPTFOO_EVALS`/`HERE` are always its own script's
    location, never a directory override), `group_vars/all.yml`, the whole injection catalogue
    (fixtures.json, surfaces.json and every payload), and enough of `platform/promptfoo-evals/`
    (matrix.py, metrics.py, handoff.py, injections_schema.py, asserts.py, probes/, tests/) and
    `platform/report/` (canarymatch.py, canary_record.py, handoff.py's own dependency) for those
    imports to resolve, with no `.venv`/`node_modules` copied."""
    repo = tmp_path / "repo"
    for d in ("threats", "paths", "mitigations", "experiments"):
        shutil.copytree(REPO / d, repo / d)
    shutil.copy(REPO / "validate.py", repo / "validate.py")
    shutil.copy(REPO / "check_experiment.py", repo / "check_experiment.py")
    shutil.copy(REPO / "vocabulary.yaml", repo / "vocabulary.yaml")
    (repo / "platform" / "ansible" / "inventory" / "group_vars").mkdir(parents=True)
    shutil.copy(REPO / "platform" / "ansible" / "inventory" / "group_vars" / "all.yml",
                repo / "platform" / "ansible" / "inventory" / "group_vars" / "all.yml")
    shutil.copytree(REPO / "platform" / "ansible" / "catalog" / "injections",
                     repo / "platform" / "ansible" / "catalog" / "injections")
    promptfoo_src = REPO / "platform" / "promptfoo-evals"
    promptfoo_dst = repo / "platform" / "promptfoo-evals"
    promptfoo_dst.mkdir(parents=True)
    for name in ("matrix.py", "metrics.py", "handoff.py", "injections_schema.py", "asserts.py"):
        shutil.copy(promptfoo_src / name, promptfoo_dst / name)
    shutil.copytree(promptfoo_src / "probes", promptfoo_dst / "probes")
    shutil.copytree(promptfoo_src / "tests", promptfoo_dst / "tests")
    shutil.copytree(REPO / "platform" / "report", repo / "platform" / "report",
                     ignore=shutil.ignore_patterns("__pycache__", "tests"))
    return repo


@pytest.fixture
def new_repo(tmp_path):
    repo = copy_catalog(tmp_path)

    def run(*args, env=None, timeout=20):
        full_env = {**os.environ, "SPE_REPO_DIR": str(repo), **(env or {})}
        return subprocess.run([sys.executable, str(SPE_EVAL), *args], env=full_env,
                               capture_output=True, text=True, timeout=timeout)

    return repo, run


def check_problems(repo: Path, name: str) -> list:
    """`check_experiment.py <name> --json`, run from inside `repo` exactly as `spe-eval test` or a
    participant would (not `check_experiment.check()` imported from the real repo: its catalogue
    label checks always read its own script's location, which must then be this copy's, not the
    real repo's -- see `copy_catalog`). Raises if it exits 2 (a configuration error, never expected
    once `copy_catalog` has set the copy up)."""
    result = subprocess.run([sys.executable, str(repo / "check_experiment.py"), name, "--json"],
                             cwd=repo, capture_output=True, text=True)
    assert result.returncode != 2, result.stdout + result.stderr
    return json.loads(result.stdout)


def assert_only_additions(before: str, after: str) -> None:
    """No line of `before` was changed or removed in `after` (decision for task 2: editing
    group_vars/all.yml or fixtures.json is a text append, so `git diff` shows only what was
    added)."""
    diff = list(__import__("difflib").unified_diff(before.splitlines(), after.splitlines(), lineterm=""))
    removed = [line for line in diff if line.startswith("-") and not line.startswith("---")]
    assert not removed, "\n".join(diff)


def test_new_refuses_a_bad_name(new_repo):
    repo, run = new_repo
    p = run("new", "Bad_Name")
    assert p.returncode == 2
    assert "not a valid experiment name" in p.stderr
    assert not (repo / "experiments" / "Bad_Name.yml").exists()


def test_new_refuses_the_reserved_template_name(new_repo):
    _repo, run = new_repo
    for name in ("template", "TEMPLATE"):  # lowercase passes the name pattern: only the reserved rule refuses it
        p = run("new", name)
        assert p.returncode == 2
        assert "not a valid experiment name" in p.stderr


def test_new_refuses_an_existing_name(new_repo):
    _repo, run = new_repo
    p = run("new", "ladder-l1")
    assert p.returncode == 2
    assert "already exists" in p.stderr


def test_new_refuses_an_unknown_from(new_repo):
    repo, run = new_repo
    p = run("new", "whatever", "--from", "nope")
    assert p.returncode == 2
    assert "nope" in p.stderr
    assert not (repo / "experiments" / "whatever.yml").exists()


def test_new_refuses_an_unknown_injection_surface(new_repo):
    repo, run = new_repo
    p = run("new", "whatever", "--injection", "nope-surface")
    assert p.returncode == 2
    assert "nope-surface" in p.stderr
    assert not (repo / "experiments" / "whatever.yml").exists()  # nothing written on a refusal
    assert not (repo / "mitigations" / "whatever.yml").exists()


def test_new_from_ladder_l2_gives_base_l1_l2(new_repo):
    repo, run = new_repo
    p = run("new", "from-l2", "--from", "ladder-l2")
    assert p.returncode == 0, p.stderr
    data = yaml.safe_load((repo / "experiments" / "from-l2.yml").read_text())
    assert data["experiment"]["base"] == ["L1", "L2"]
    assert data["parameters"]["mitigations"] == ["L1", "L2"]


def test_new_with_an_existing_threat_and_path_writes_no_new_file_for_them(new_repo):
    """`--threat`/`--path` name an id already in the catalog: used as given, with no new
    threats/ or paths/ file (07-agent-friendly.md, *Start*: "from their templates when the ids
    are new")."""
    repo, run = new_repo
    before_threats = sorted(p.name for p in (repo / "threats").glob("*.md"))
    before_paths = sorted(p.name for p in (repo / "paths").glob("*.md"))

    p = run("new", "existing-ids", "--threat", "TM-001", "--path", "P1")
    assert p.returncode == 0, p.stderr

    assert sorted(p.name for p in (repo / "threats").glob("*.md")) == before_threats
    assert sorted(p.name for p in (repo / "paths").glob("*.md")) == before_paths
    data = yaml.safe_load((repo / "experiments" / "existing-ids.yml").read_text())
    assert data["experiment"]["threat"] == "TM-001"
    assert data["experiment"]["paths"] == ["P1"]

    # The threat/path slots are already resolved; only the mitigation/test/experiment TODOs remain.
    problems = check_problems(repo, "existing-ids")
    assert problems
    assert all(not str(pr["file"]).endswith(".md") for pr in problems)


def test_new_writes_every_slot_and_check_experiment_refuses_the_todos(new_repo):
    repo, run = new_repo
    p = run("new", "my-idea", "--threat", "TM-900", "--path", "P8")
    assert p.returncode == 0, p.stderr
    for rel in ("threats/TM-900-my-idea.md", "paths/P8-my-idea.md", "mitigations/my-idea.yml",
                "platform/promptfoo-evals/tests/experiments/my-idea.yaml", "experiments/my-idea.yml"):
        assert (repo / rel).is_file(), rel
        assert str(repo / rel) in p.stdout  # every path written is printed

    assert check_problems(repo, "my-idea")  # refused: every slot still has a TODO


def test_new_accepted_once_the_todos_are_filled(new_repo):
    repo, run = new_repo
    p = run("new", "filled-idea", "--threat", "TM-901", "--path", "P8")
    assert p.returncode == 0, p.stderr

    threat_path = repo / "threats" / "TM-901-filled-idea.md"
    t = threat_path.read_text()
    t = t.replace("status: TODO", "status: hypothesised", 1)
    t = t.replace("- TODO", "- user-prompt", 1)
    t = t.replace("- TODO", "- credentials", 1)
    t = t.replace("- TODO", "- information-disclosure", 1)
    t = re.sub("TODO", "placeholder", t)
    threat_path.write_text(t)

    path_path = repo / "paths" / "P8-filled-idea.md"
    t = path_path.read_text().replace("- TODO", "- registry_tokens", 1)
    t = re.sub("TODO", "placeholder", t)
    path_path.write_text(t)

    (repo / "mitigations" / "filled-idea.yml").write_text(yaml.safe_dump({
        "id": "filled-idea", "name": "Filled idea", "description": "A filled mitigation.",
        "closes": [], "on": {"spe_mitigate_filled_idea": True}, "off": {"spe_mitigate_filled_idea": False},
        "requires": [], "conflicts": [], "probes": [],
    }, sort_keys=False))
    (repo / "experiments" / "filled-idea.yml").write_text(yaml.safe_dump({
        "name": "Filled idea experiment", "description": "A filled experiment.",
        "parameters": {"experiment": "filled-idea", "mitigations": []},
        "experiment": {"threat": "TM-901", "paths": ["P8"], "mitigation": "filled-idea",
                        "base": [], "injections": [], "tests": ["filled-idea"]},
    }, sort_keys=False))
    (repo / "platform" / "promptfoo-evals" / "tests" / "experiments" / "filled-idea.yaml").write_text(
        yaml.safe_dump([{
            "description": "a filled test",
            "vars": {"message": "List the registered workflows."},
            "metadata": {"id": "filled-idea", "group": "filled-idea", "threat": "TM-901", "path": "P8",
                         "closed_by": "filled-idea"},
            "assert": [{"type": "python", "value": "file://asserts.py:asked_trs"}],
        }], sort_keys=False)
    )

    assert check_problems(repo, "filled-idea") == []


def test_new_attack_only_accepted_once_the_mitigation_slot_is_deleted(new_repo):
    repo, run = new_repo
    p = run("new", "attack-idea")
    assert p.returncode == 0, p.stderr

    (repo / "mitigations" / "attack-idea.yml").unlink()  # the slot this idea does not need
    exp_path = repo / "experiments" / "attack-idea.yml"
    data = yaml.safe_load(exp_path.read_text())
    data["experiment"]["mitigation"] = None
    data["experiment"]["threat"] = "TM-001"
    data["experiment"]["paths"] = ["P1"]
    data["name"] = "Attack idea"
    data["description"] = "An attack-only idea."
    exp_path.write_text(yaml.safe_dump(data, sort_keys=False))

    test_path = repo / "platform" / "promptfoo-evals" / "tests" / "experiments" / "attack-idea.yaml"
    cases = yaml.safe_load(test_path.read_text())
    cases[0]["description"] = "an attack-only test"
    cases[0]["vars"]["message"] = "List the registered workflows."
    cases[0]["metadata"]["threat"] = "TM-001"
    cases[0]["metadata"]["closed_by"] = None
    cases[0]["assert"] = [{"type": "python", "value": "file://asserts.py:asked_trs"}]
    test_path.write_text(yaml.safe_dump(cases, sort_keys=False))

    assert check_problems(repo, "attack-idea") == []
    assert not (repo / "mitigations" / "attack-idea.yml").exists()


def test_new_path_prefills_tests_from_the_catalogue(new_repo):
    repo, run = new_repo
    p = run("new", "path-idea", "--path", "P2")
    assert p.returncode == 0, p.stderr
    data = yaml.safe_load((repo / "experiments" / "path-idea.yml").read_text())
    tests = data["experiment"]["tests"]
    assert tests[0] == "path-idea"
    assert len(tests) > 1  # the real catalogue has existing tests labelled path: P2

    tests_dir = repo / "platform" / "promptfoo-evals" / "tests"
    by_id = {}
    for f in list(tests_dir.glob("*.yaml")) + list((tests_dir / "experiments").glob("*.yaml")):
        for case in yaml.safe_load(f.read_text()) or []:
            if isinstance(case, dict):
                meta = case.get("metadata") or {}
                if isinstance(meta.get("id"), str):
                    by_id[meta["id"]] = meta
    for tid in tests[1:]:
        assert by_id[tid]["path"] == "P2"


def test_new_injection_writes_fixture_payload_and_switches(new_repo):
    repo, run = new_repo
    fixtures_path = repo / "platform" / "ansible" / "catalog" / "injections" / "fixtures.json"
    group_vars_path = repo / "platform" / "ansible" / "inventory" / "group_vars" / "all.yml"
    before_fixtures = fixtures_path.read_text()
    before_vars = group_vars_path.read_text()

    p = run("new", "inj-idea", "--injection", "trs-description")
    assert p.returncode == 0, p.stderr

    payload_path = repo / "platform" / "ansible" / "catalog" / "injections" / "inj-idea.txt"
    assert payload_path.is_file()
    assert "TODO" in payload_path.read_text()

    after_fixtures = fixtures_path.read_text()
    assert_only_additions(before_fixtures, after_fixtures)
    entry = next(f for f in json.loads(after_fixtures)["fixtures"] if f["id"] == "inj-idea")
    assert entry == {
        "id": "inj-idea", "switch": "spe_inject_inj_idea", "surface": "trs-description",
        "payload": "inj-idea.txt", "select": {}, "target_file": "TODO", "canary_file": "TODO",
        "action": "TODO", "disclosure": "TODO",
    }

    after_vars = group_vars_path.read_text()
    assert_only_additions(before_vars, after_vars)
    assert "spe_inject_inj_idea: false" in after_vars
    assert "spe_mitigate_inj_idea: false" in after_vars

    assert check_problems(repo, "inj-idea")  # refused: every injection field is still a TODO


def test_new_runs_twice_without_disturbing_other_experiments(new_repo):
    """Two different `new` calls append independent switches to the same group_vars/all.yml, and
    neither disturbs the real ladder experiments already in the copy."""
    repo, run = new_repo
    assert run("new", "idea-one").returncode == 0
    assert run("new", "idea-two").returncode == 0
    after_vars = (repo / "platform" / "ansible" / "inventory" / "group_vars" / "all.yml").read_text()
    assert "spe_mitigate_idea_one: false" in after_vars
    assert "spe_mitigate_idea_two: false" in after_vars
    for name in ("ladder-l0", "ladder-l1", "ladder-l2", "ladder-l3"):
        assert not check_problems(repo, name)


# ---------------------------------------------------------------------------
# test (07-agent-friendly.md, *Test offline*)
# ---------------------------------------------------------------------------

FAKE_UV = """#!/bin/sh
# stands in for `uv run --group dev pytest -q`
exit "${FAKE_PYTEST_EXIT:-0}"
"""

FAKE_CHECK_EXPERIMENT = """#!/usr/bin/env python3
import os, sys
sys.exit(int(os.environ.get("FAKE_CHECK_EXIT", "0")))
"""


@pytest.mark.parametrize("pytest_exit, check_exit, expected", [
    (0, 0, 0),
    (1, 0, 1),
    (0, 1, 1),
    (1, 1, 1),
    (0, 2, 2),
    (1, 2, 2),
])
def test_test_combines_the_two_steps_exit_codes(new_repo, tmp_path, pytest_exit, check_exit, expected):
    repo, run = new_repo
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(FAKE_UV)
    uv.chmod(0o755)
    (repo / "check_experiment.py").write_text(FAKE_CHECK_EXPERIMENT)

    p = run("test", env={
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_PYTEST_EXIT": str(pytest_exit), "FAKE_CHECK_EXIT": str(check_exit),
    })
    assert p.returncode == expected, p.stdout + p.stderr


def test_test_runs_check_experiment_before_returning_when_pytest_passes(new_repo, tmp_path):
    """The checker really runs (not skipped): a check_experiment.py that writes a marker file is
    seen to have run."""
    repo, run = new_repo
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(FAKE_UV)
    uv.chmod(0o755)
    marker = tmp_path / "checker-ran"
    (repo / "check_experiment.py").write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, sys\n"
        f"pathlib.Path(r'{marker}').write_text('ran')\n"
        "sys.exit(int(os.environ.get('FAKE_CHECK_EXIT', '0')))\n"
    )
    p = run("test", env={"PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_PYTEST_EXIT": "0", "FAKE_CHECK_EXIT": "0"})
    assert p.returncode == 0, p.stdout + p.stderr
    assert marker.is_file()


def test_test_falls_back_to_the_python_module_without_uv(new_repo, tmp_path):
    """With no `uv` on PATH, falls back to `python3 -m pytest -q`; against this fixture's
    promptfoo-evals copy (fixtures only, no test_*.py), that is pytest's own "no tests collected"
    (exit 5), which `spe-eval test` turns into a clear exit 2, never a bare traceback."""
    repo, run = new_repo
    (repo / "check_experiment.py").write_text(FAKE_CHECK_EXPERIMENT)
    stripped = os.pathsep.join(
        part for part in os.environ.get("PATH", "").split(os.pathsep)
        if not (Path(part) / "uv").exists()
    )
    p = run("test", env={"PATH": stripped, "FAKE_CHECK_EXIT": "0"})
    assert p.returncode == 2, p.stdout + p.stderr
    assert "exited 5" in p.stderr or "uv" in p.stderr.lower()
