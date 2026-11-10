"""The `spe-eval` command line (experiments spec part 03, decisions 7, 9, 11, 18, 22; part 07's
command table): `arm`, `run` (with `--detach`), `status`, `wait`, `runs`. Fakes `spe-apply`,
`run.sh` and `systemd-run` so no real Ansible, Docker or model call happens; a tiny two-experiment
catalogue (`one-arm`, `two-arm`) keeps each test fast and independent of the real `experiments/`/
`mitigations/` files (those are exercised against the real catalogue by `test_spe_eval.py`).
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parents[2]  # platform/dev/tests -> platform
SPE_EVAL = HERE / "instance" / "spe-eval"

FAKE_SPE_APPLY = """#!/bin/sh
echo "$*" >> "$FAKE_SPE_APPLY_LOG"
case "$1" in
  status) echo "agent /healthz: ${FAKE_HEALTH_STATUS:-200}"; exit 0 ;;
  *) exit "${FAKE_SPE_APPLY_EXIT:-0}" ;;
esac
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

FAKE_SYSTEMD_RUN = """#!/bin/sh
echo "$*" >> "$FAKE_SYSTEMD_RUN_LOG"
exit 0
"""


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

    def run(*args, env=None, timeout=20):
        full_env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(home),
                    "SPE_REPO_DIR": str(repo), "FAKE_SPE_APPLY_LOG": str(log_apply),
                    "FAKE_RUN_SH_LOG": str(log_run_sh), "FAKE_SYSTEMD_RUN_LOG": str(log_systemd),
                    "SPE_EVAL_HEALTH_INTERVAL": "0.01", "SPE_EVAL_HEALTH_TIMEOUT": "0.3",
                    "SPE_EVAL_WAIT_INTERVAL": "0.05", **(env or {})}
        return subprocess.run([sys.executable, str(SPE_EVAL), *args], env=full_env, capture_output=True,
                               text=True, timeout=timeout)

    def popen(*args, env=None):
        full_env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(home),
                    "SPE_REPO_DIR": str(repo), "FAKE_SPE_APPLY_LOG": str(log_apply),
                    "FAKE_RUN_SH_LOG": str(log_run_sh), "FAKE_SYSTEMD_RUN_LOG": str(log_systemd),
                    "SPE_EVAL_HEALTH_INTERVAL": "0.01", "SPE_EVAL_HEALTH_TIMEOUT": "0.3",
                    "SPE_EVAL_WAIT_INTERVAL": "0.05", **(env or {})}
        return subprocess.Popen([sys.executable, str(SPE_EVAL), *args], env=full_env, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)

    def calls(log_path: Path) -> list[str]:
        return log_path.read_text().splitlines() if log_path.exists() else []

    return run, popen, calls, repo, home, {"apply": log_apply, "run_sh": log_run_sh, "systemd": log_systemd}


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
    assert any(c == "status" for c in apply_calls)


def test_arm_exits_1_when_the_stack_never_answers(setup):
    run, _popen, _calls, _repo, _home, _logs = setup
    p = run("arm", "one-arm", "baseline", env={"FAKE_HEALTH_STATUS": "503"})
    assert p.returncode == 1, p.stdout
    assert "did not answer in time" in p.stderr


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

    windows = (home / "spe-eval" / "windows.jsonl").read_text().splitlines()
    assert len(windows) == 1
    window = json.loads(windows[0])
    assert window["run"] == "20261110T100000Z" and window["experiment"] == "two-arm"


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


def test_run_detach_prints_the_run_id_and_returns_at_once(setup):
    run, _popen, calls, _repo, _home, logs = setup
    started = time.monotonic()
    p = run("run", "one-arm", "--detach")
    elapsed = time.monotonic() - started
    assert p.returncode == 0, p.stderr
    run_id = p.stdout.strip()
    assert re.fullmatch(r"\d{8}T\d{6}Z", run_id)
    assert elapsed < 5  # the fake systemd-run exits at once; a real one would too (R5)
    systemd_calls = calls(logs["systemd"])
    assert len(systemd_calls) == 1
    assert f"--unit=spe-eval-{run_id}" in systemd_calls[0]
    assert f"SPE_EVAL_RUN_ID={run_id}" in systemd_calls[0]
    assert "run one-arm --repeat 1" in systemd_calls[0]


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


def test_runs_ordering_and_json_fields(setup):
    run, _popen, _calls, _repo, home, _logs = setup
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
    assert home  # the fixture's home dir backs both runs (sanity: no stray state leaks across runs)


def test_runs_text_output_with_none_yet(setup):
    run, _popen, _calls, _repo, _home, _logs = setup
    p = run("runs")
    assert p.returncode == 0, p.stderr
    assert "none yet" in p.stdout
