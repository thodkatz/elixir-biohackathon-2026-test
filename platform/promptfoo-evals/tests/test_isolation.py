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



def test_vm_runner_timeout_is_an_isolation_error(hdir, monkeypatch):
    # A hung SSH or docker call must fail as the step it was (RestoreError, StateError), not as TimeoutExpired.
    def hang(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    monkeypatch.setattr(isolation, "vm_argv", lambda d: [])
    monkeypatch.setattr(isolation.subprocess, "run", hang)
    with pytest.raises(isolation.StateError, match="timed out"):
        isolation.baseline(hdir)
    with pytest.raises(isolation.RestoreError, match="timed out"):
        isolation.restore(hdir)

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


TOOLS = [{"id": "wes-drs-smoke", "versions": [{"id": "1.0.0", "descriptor_type": ["NFL"]}]},
         {"id": "x", "versions": [{"id": "2", "descriptor_type": ["NFL"]}]}]
RUNS = {"": {"runs": [{"run_id": "R1", "state": "COMPLETE"}], "next_page_token": "p2"},
        "p2": {"runs": [{"run_id": "R2", "state": "RUNNING"}], "next_page_token": ""}}
RECORDED = {"/trs/tools": TOOLS, "/wes/runs/R2": {"run_id": "R2", "request": {
    "workflow_url": "trs://h/x/2/NFL/main.nf", "workflow_params": "{\"a\": 1}"}},
    "/trs/tools/x/versions/2/NFL/files": [{"path": "main.nf", "file_type": "PRIMARY_DESCRIPTOR"}],
    "/trs/tools/x/versions/2/NFL/descriptor/main.nf": {"content": "process A {}", "url": "u"}}


@pytest.fixture
def api():
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            path, _, query = self.path.partition("?")
            body = RUNS[query.removeprefix("page_token=")] if path == "/wes/runs" else RECORDED.get(path)
            self.send_response(200 if body is not None else 404)
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_state_script_against_recorded_api(api, tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "sub" / "b.txt").write_text("b")
    env = {**os.environ, "TRS_BASE": f"{api}/trs", "WES_BASE": f"{api}/wes", "SPE_SANDBOX_HOME": str(tmp_path),
           "SPE_STATE_DETAILS": json.dumps({"runs": ["R2"], "tools": [["x", "2"]]})}
    out = subprocess.run([sys.executable, "-"], input=isolation.STATE_PY, env=env, capture_output=True,
                         text=True, check=True).stdout
    state = json.loads(out)
    assert sorted(state["trs"]) == ["wes-drs-smoke/1.0.0", "x/2"]
    assert state["trs"]["x/2"]["descriptor_types"] == ["NFL"]
    assert state["wes"] == {"R1": "COMPLETE", "R2": "RUNNING"}
    assert state["runs"]["R2"] == {"workflow_url": "trs://h/x/2/NFL/main.nf", "workflow_params": {"a": 1}}
    assert state["tools"]["x/2"] == {"descriptor_urls": [f"{api}/trs/tools/x/versions/2/NFL/descriptor/main.nf"],
                                     "descriptors": {"main.nf": "process A {}"}}
    assert state["sandbox"] == ["a.txt", "sub/b.txt"]


def _state(trs, wes, sandbox, runs=None, tools=None):
    return json.dumps({"trs": {k: {"id": k.split("/")[0], "version": k.split("/")[1], "descriptor_types": ["NFL"]}
                               for k in trs}, "wes": wes, "sandbox": sandbox,
                       "runs": runs or {}, "tools": tools or {}})


def test_baseline_and_state_diff(hdir):
    answers = iter([_state(["wes-drs-smoke/1.0.0"], {"R1": "COMPLETE"}, ["a.txt"]),
                    _state(["wes-drs-smoke/1.0.0", "x/2"], {"R1": "COMPLETE", "R2": "RUNNING"}, ["a.txt", "n.sh"]),
                    _state([], {}, [], runs={"R2": {"workflow_url": "trs://h/x/2/NFL/main.nf",
                                                    "workflow_params": {"a": 1}}},
                           tools={"x/2": {"descriptor_urls": ["u"], "descriptors": {"main.nf": "process A {}"}}})])
    calls = []

    def run(argv, stdin=None):
        if argv[:2] == ["sh", "-c"]:  # the test receiver's log: not deployed here
            return cp(out="absent\n")
        calls.append(argv)
        assert argv[:3] == ["docker", "exec", "-i"] and argv[-3:] == [isolation.SANDBOX, "python3", "-"]
        assert stdin == isolation.STATE_PY
        return cp(out=next(answers))

    base = isolation.baseline(hdir, run=run)
    assert base == {"trs": ["wes-drs-smoke/1.0.0"], "wes": ["R1"], "sandbox": ["a.txt"], "sink": None}
    assert isolation.state_diff(hdir, base, run=run) == {
        "trs_tools_added": [{"id": "x", "version": "2", "descriptor_urls": ["u"],
                             "descriptors": {"main.nf": "process A {}"}}],
        "wes_runs_added": [{"run_id": "R2", "workflow_url": "trs://h/x/2/NFL/main.nf", "workflow_params": {"a": 1},
                            "state": "RUNNING"}],
        "sandbox_files_added": ["n.sh"], "sink_requests_added": None}
    assert json.loads(calls[2][calls[2].index("-e") + 1].split("=", 1)[1]) == {"runs": ["R2"], "tools": [["x", "2"]]}


def test_state_diff_with_nothing_new_makes_one_call(hdir):
    same = _state(["t/1"], {"R1": "COMPLETE"}, [])
    calls = []
    diff = isolation.state_diff(hdir, {"trs": ["t/1"], "wes": ["R1"], "sandbox": [], "sink": None},
                                run=lambda argv, stdin=None: calls.append(argv) or cp(
                                    out="absent" if argv[0] == "sh" else same))
    assert diff == {"trs_tools_added": [], "wes_runs_added": [], "sandbox_files_added": [],
                    "sink_requests_added": None}
    assert len([c for c in calls if c[0] == "docker"]) == 1


def _receiver(size_then, size_now, appended):
    sizes = iter([size_then, size_now])

    def run(argv, stdin=None):
        if argv[:2] == ["sh", "-c"]:
            assert argv[-1] == isolation.SINK_LOG
            if "wc -c" in argv[2]:
                return cp(out=f"{next(sizes)}\n")
            assert argv[-2] == str(size_then)
            return cp(out="".join(json.dumps(r) + "\n" for r in appended))
        return cp(out=_state([], {}, []))
    return run


def test_receiver_requests_since_the_baseline(hdir):
    got = [{"method": "POST", "host": "backup.spe-eval.test:8099", "path": "/upload", "body": "summary"}]
    run = _receiver(120, 260, got)
    base = isolation.baseline(hdir, run=run)
    assert base["sink"] == 120
    assert isolation.state_diff(hdir, base, run=run)["sink_requests_added"] == got


def test_no_receiver_is_none_not_empty(hdir):
    run = _receiver("absent", "absent", [])
    base = isolation.baseline(hdir, run=run)
    assert base["sink"] is None and isolation.state_diff(hdir, base, run=run)["sink_requests_added"] is None


def test_a_shrunk_receiver_log_is_an_error(hdir):
    # A receiver restarted with a new log would make "nothing appended" look like "nothing received".
    run = _receiver(120, 40, [])
    with pytest.raises(isolation.StateError, match="receiver"):
        isolation.state_diff(hdir, isolation.baseline(hdir, run=run), run=run)


@pytest.mark.parametrize("answer", [cp(1, err="Traceback"), cp(out="not json")])
def test_state_read_failure_is_an_error(hdir, answer):
    with pytest.raises(isolation.StateError):
        isolation.baseline(hdir, run=lambda argv, stdin=None: answer)


def test_state_diff_rejects_a_malformed_baseline(hdir):
    with pytest.raises(isolation.StateError):
        isolation.state_diff(hdir, {"trs": "x"}, run=lambda argv, stdin=None: cp(out=_state([], {}, [])))


@pytest.fixture
def hooked(hdir, tmp_path, monkeypatch):
    seen = {"snapshot": 0, "restore": iter([30.0, 50.0, 40.0])}
    monkeypatch.setenv("SPE_EVAL_BASELINE", str(tmp_path / "rep" / ".baseline.json"))
    monkeypatch.setattr(isolation, "handoff_dir", lambda: hdir)
    monkeypatch.setattr(isolation, "snapshot_exists", lambda d: seen.get("exists", False))
    monkeypatch.setattr(isolation, "snapshot", lambda d: seen.__setitem__("snapshot", seen["snapshot"] + 1))
    monkeypatch.setattr(isolation, "restore", lambda d: next(seen["restore"]))
    monkeypatch.setattr(isolation, "baseline", lambda d: {"trs": ["t/1"], "wes": [], "sandbox": [], "sink": None})
    return seen


def test_before_all_snapshots_only_when_missing(hooked):
    assert isolation.extension_hook("beforeAll", {"suite": {}}) is None
    hooked["exists"] = True
    isolation.extension_hook("beforeAll", {"suite": {}})
    assert hooked["snapshot"] == 1


def test_before_each_restores_then_writes_baseline_and_restore_seconds(hooked, hdir):
    (hdir / "hardening.json").write_text(json.dumps({"schema_version": 1, "restore_seconds": None}))
    for _ in range(3):
        assert isolation.extension_hook("beforeEach", {"test": {"vars": {}}}) is None
    assert isolation.read_baseline() == {"trs": ["t/1"], "wes": [], "sandbox": [], "sink": None}
    assert json.loads((hdir / "hardening.json").read_text())["restore_seconds"] == 40.0
    assert json.loads((hdir / "restore_times.json").read_text()) == {"generated_at": STAMP,
                                                                     "seconds": [30.0, 50.0, 40.0]}


def test_restore_times_reset_when_the_build_changes(hdir):
    (hdir / "restore_times.json").write_text(json.dumps({"generated_at": "2026-01-01T00:00:00Z", "seconds": [999]}))
    assert isolation.record_restore_seconds(hdir, 20.0) == 20.0
    assert not (hdir / "hardening.json").exists()


def test_before_each_restore_failure_raises_and_leaves_no_baseline(hooked, monkeypatch):
    isolation.write_baseline({"trs": ["stale/1"], "wes": [], "sandbox": []})

    def broken(d):
        raise isolation.RestoreError("stack not healthy after 300s: rest-1")

    monkeypatch.setattr(isolation, "restore", broken)
    with pytest.raises(isolation.RestoreError):
        isolation.extension_hook("beforeEach", {"test": {}})
    with pytest.raises(isolation.StateError):
        isolation.read_baseline()


def test_after_each_logs_counts_and_never_raises(hooked, monkeypatch, capsys):
    isolation.write_baseline({"trs": [], "wes": [], "sandbox": []})
    monkeypatch.setattr(isolation, "state_diff", lambda d, b: {"trs_tools_added": [{"id": "x"}],
                                                               "wes_runs_added": [], "sandbox_files_added": []})
    assert isolation.extension_hook("afterEach", {"test": {}, "result": {}}) is None
    assert "trs_tools_added=1" in capsys.readouterr().err
    monkeypatch.setattr(isolation, "state_diff", lambda d, b: (_ for _ in ()).throw(isolation.StateError("down")))
    isolation.extension_hook("afterEach", {"test": {}, "result": {}})
    assert "state diff unavailable" in capsys.readouterr().err


def test_other_hooks_do_nothing_and_default_baseline_path(monkeypatch):
    assert isolation.extension_hook("afterAll", {"suite": {}}) is None
    monkeypatch.delenv("SPE_EVAL_BASELINE", raising=False)
    assert isolation.baseline_path() == Path(isolation.__file__).resolve().parent / "reports" / ".baseline.json"
