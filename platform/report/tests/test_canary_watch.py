"""canary_watch.py: the hits file, the scan of one archived run, and discover (decisions 3, 5, 9,
10). The fixture run in fixtures/canary/run/ is laid out as run_archive writes it, with made-up
tokens only."""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import canary_hits  # noqa: E402
import canary_record  # noqa: E402
import canary_watch  # noqa: E402
from canary_hits import HitsFile  # noqa: E402

HERE = Path(__file__).resolve().parent
RUN = HERE / "fixtures" / "canary" / "run"
WATCH = HERE.parent / "canary_watch.py"
API_HOST = "api.spe.test"
WORKSPACE = "6f1c2a9e-3b7d-4e1a-9c2f-0a1b2c3d4e5f"
META = {"workspace": WORKSPACE, "instance": "fixture", "owner": "alice"}
TOKENS = [t["token"] for t in canary_record.load_canaries(RUN)]


def scan(tmp_path: Path, seen: set[str] | None = None, run: Path = RUN) -> tuple[HitsFile, int]:
    hits = HitsFile(str(tmp_path / "hits.jsonl"))
    return hits, canary_watch.scan_archive(str(run), hits, set() if seen is None else seen, META, API_HOST, "archive")


def test_archive_one_hit_per_canary_and_place(tmp_path):
    hits, count = scan(tmp_path)
    records = hits.read()
    assert count == len(records)
    r1 = [h for h in records if h["run"] == "r1"]
    keys = [(h["place"], (h["tool"] or {}).get("call_id"), h["canary"]["token"]) for h in r1]
    assert len(keys) == len(set(keys))  # one hit per canary and place, not one per copy
    assert sorted(keys, key=str) == sorted([
        ("prompt", None, "FCANARY-TEST011"),
        ("tool_args", "call1", "FCANARY-TEST01"),
        ("tool_result", "call2", "FCANARY-TEST01"),
        ("tool_args", "call3", "FCANARY-TEST01"),
        ("answer", None, "FCANARY-TEST01"),
    ], key=str)
    assert {h["source"] for h in r1} == {"agui-journal"}  # journals first: their copy wins
    assert {h["frontend"] for h in r1} == {"agui"}
    # The run only the run log has still gives its hit.
    assert [(h["source"], h["kind"]) for h in records if h["run"] == "r9"] == [("agent-runs", "answer")]
    # agui/openwebui-export.json (the journals reshaped) is never read.
    assert not [h for h in records if h["frontend"] == "openwebui" and h["session"]["id"] == "s1"]
    for h in records:
        assert {k: h[k] for k in META} == META
        assert h["detected"].endswith("Z")
        assert set(h) == {"id", "detected", "at", "workspace", "instance", "owner", "frontend", "source", "session",
                          "run", "prompt", "kind", "place", "tool", "canary", "excerpt"}


def test_archive_reads_openwebui_export(tmp_path):
    hits, _ = scan(tmp_path)
    owui = [h for h in hits.read() if h["frontend"] == "openwebui"]
    assert [(h["session"]["id"], h["run"], h["kind"], h["source"]) for h in owui] == [
        ("owc1", "a1", "touched", "archive")]


def test_openwebui_resaved_once(tmp_path):
    seen: set[str] = set()
    hits, first = scan(tmp_path, seen)
    assert first > 0
    assert canary_watch.scan_archive(str(RUN), hits, seen, META, API_HOST, "archive") == 0
    assert len(hits.read()) == first


def test_openwebui_live_then_archive_once(tmp_path):
    """A chat read live from the database, then in the archive's export: one hit per canary and place."""
    hits = HitsFile(str(tmp_path / "hits.jsonl"))
    seen: set[str] = set()
    canaries = canary_record.load_canaries(RUN)
    chat = json.loads((RUN / "openwebui-export.json").read_text())["chats"][0]
    row = {"id": chat["id"], "title": chat["title"], "chat": json.dumps(chat["chat"])}
    for place in canary_hits.openwebui_places(row, "openwebui-db"):
        for hit in canary_hits.hits_for(place, canaries, API_HOST):
            hit |= META
            seen.add(canary_hits.dedup_key(hit, "g1"))
            hits.append(hit)
    canary_watch.scan_archive(str(RUN), hits, seen, META, API_HOST, "g1")
    owui = [h for h in hits.read() if h["frontend"] == "openwebui"]
    assert [h["source"] for h in owui] == ["openwebui-db"]


def test_ids_are_line_numbers(tmp_path):
    hits, _ = scan(tmp_path)
    lines = (tmp_path / "hits.jsonl").read_text().splitlines()
    assert [json.loads(line)["id"] for line in lines] == list(range(1, len(lines) + 1))
    assert [h["id"] for h in hits.read(after=2)] == list(range(3, len(lines) + 1))
    # A second HitsFile on the same path carries on from the last line.
    again = HitsFile(str(tmp_path / "hits.jsonl"))
    assert again.append({"kind": "answer"}) == len(lines) + 1


def test_hits_file_mode_0640(tmp_path):
    old = os.umask(0o077)  # tighter than 0640: only the fchmod gives group read
    try:
        hits = HitsFile(str(tmp_path / "hits.jsonl"))
        hits.append({"kind": "answer"})
    finally:
        os.umask(old)
    assert stat.S_IMODE(os.stat(tmp_path / "hits.jsonl").st_mode) == 0o640


def test_hits_file_read_survives_a_cut_multibyte_line(tmp_path):
    path = tmp_path / "hits.jsonl"
    whole = json.dumps({"id": 1, "excerpt": "\u00e9t\u00e9"}, ensure_ascii=False).encode() + b"\n"
    cut = json.dumps({"id": 2, "excerpt": "\u00e9"}, ensure_ascii=False).encode()[:-3] + b"\xc3"
    path.write_bytes(whole + cut)
    assert [h["id"] for h in HitsFile(str(path)).read()] == [1]


def test_hits_file_cap(tmp_path):
    hits = HitsFile(str(tmp_path / "hits.jsonl"), max_bytes=2000)
    ids = [hits.append({"excerpt": "x" * 300}) for _ in range(10)]
    assert None in ids
    assert hits.full
    kept = [i for i in ids if i is not None]
    assert kept == list(range(1, len(kept) + 1))
    assert ids[len(kept):] == [None] * (10 - len(kept))
    assert os.path.getsize(tmp_path / "hits.jsonl") <= 2000
    assert hits.append({"kind": "answer"}) is None


def test_meta_from_run_yml_without_report(tmp_path):
    run = tmp_path / "run"
    shutil.copytree(RUN, run)
    (run / "report.json").unlink()
    assert canary_watch.archive_meta(str(run)) == {"workspace": None, "instance": "fixture", "owner": "alice"}
    assert canary_watch.archive_meta(str(RUN)) == META


def test_cli_logs_no_token(tmp_path):
    out = tmp_path / "hits.jsonl"
    page = tmp_path / "hits.html"
    done = subprocess.run([sys.executable, str(WATCH), "--archive", str(RUN), "--out", str(out),
                           "--html", str(page), "--api-host", API_HOST], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    logs = done.stdout + done.stderr
    assert logs.strip()
    assert TOKENS
    for token in TOKENS:
        assert token not in logs
    assert "FCANARY" not in logs and "MCANARY" not in logs
    assert stat.S_IMODE(page.stat().st_mode) == 0o640
    assert "<mark>" in page.read_text()
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []  # no temp file left
    assert len(out.read_text().splitlines()) > 0
    assert {json.loads(line)["workspace"] for line in out.read_text().splitlines()} == {WORKSPACE}


def test_cli_missing_record_fails_without_token(tmp_path):
    run = tmp_path / "run"
    shutil.copytree(RUN, run)
    (run / "canaries.json").unlink()
    done = subprocess.run([sys.executable, str(WATCH), "--archive", str(run), "--out", str(tmp_path / "h.jsonl")],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode != 0
    assert "canaries.json" in done.stderr


def test_lone_surrogate_in_a_source_line(tmp_path):
    """Untrusted JSON can carry a lone surrogate ("\\ud800"): the scan completes, the hit is kept, and
    the hits file stays valid UTF-8 JSON (the surrogate written as U+FFFD, offsets unchanged)."""
    run = tmp_path / "run"
    shutil.copytree(RUN, run)
    record = {"run_id": "r8\udc00", "thread_id": "s8\udc00", "started": 1793714800.0, "input": "go", "tool_calls": [],
              "answer": "\ud800 The flag is FCANARY-TEST01."}
    with open(run / "agui" / "agent-runs.jsonl", "a") as f:
        f.write(json.dumps(record) + "\n")  # ensure_ascii: the line holds the \ud800 escape
    hits, count = scan(tmp_path, run=run)
    raw = (tmp_path / "hits.jsonl").read_bytes()
    raw.decode("utf-8")  # strict: valid UTF-8
    records = hits.read()
    assert count == len(records)
    r8 = [h for h in records if h["run"] == "r8\ufffd"]  # a surrogate in the run id too
    assert [(h["kind"], h["canary"]["token"]) for h in r8] == [("answer", "FCANARY-TEST01")]
    excerpt = r8[0]["excerpt"]
    assert excerpt["text"].startswith("� ")
    assert excerpt["text"][excerpt["start"]:excerpt["end"]] == "FCANARY-TEST01"
    assert [h["session"]["id"] for h in records if h["frontend"] == "openwebui"] == ["owc1"]  # later hits kept


def test_cli_rerun_with_surrogate_adds_nothing(tmp_path):
    """The key of a hit read back from the file (surrogate written as U+FFFD) matches a fresh scan's."""
    run = tmp_path / "run"
    shutil.copytree(RUN, run)
    with open(run / "agui" / "agent-runs.jsonl", "a") as f:
        f.write(json.dumps({"run_id": "r8\udc00", "thread_id": "s8", "answer": "FCANARY-TEST01 \ud800"}) + "\n")
    out = tmp_path / "hits.jsonl"
    argv = [sys.executable, str(WATCH), "--archive", str(run), "--out", str(out), "--api-host", API_HOST]
    assert subprocess.run(argv, capture_output=True, timeout=60).returncode == 0
    lines = out.read_text().splitlines()
    done = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and " 0 new hits" in done.stdout
    assert out.read_text().splitlines() == lines


# --- discover: which Coder workspaces the watcher scans, and their generations (decision 9) ---

WS1 = "11111111-1111-1111-1111-111111111111"
WS2 = "22222222-2222-2222-2222-222222222222"


def _hosts_yml(path: Path, api_host: str = "api.spe.test", ssh_target: str = "localhost") -> None:
    path.write_text(
        "instance: " + path.parent.name + "\n"
        "api_host: " + api_host + "\n"
        "ssh_user: ubuntu\n"
        "provision: existing\n"
        "ssh_target: " + ssh_target + "\n"
    )


def _sidecar(reports_dir: Path, workspace_id: str, instance: str, owner: str = "alice") -> Path:
    path = reports_dir / f"{workspace_id}.json"
    path.write_text(json.dumps({"owner": owner, "workspace": f"{owner}-ws", "instance": instance,
                                "created": "2026-11-10 14:00 UTC", "parameters": {}}))
    return path


def _output_dir(output_root: Path, instance: str, encrypted: bool = False, no_record: bool = False) -> Path:
    directory = output_root / instance
    directory.mkdir(parents=True)
    _hosts_yml(directory / "hosts.yml")
    if no_record:
        pass
    elif encrypted:
        (directory / "canaries.json.age").write_text("age-encrypted-stub")
    else:
        (directory / "canaries.json").write_text(json.dumps(
            {"tokens": [{"token": "FCANARY-TEST01", "type": "file", "file": "flag.txt"}]}))
    return directory


def _layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    reports = tmp_path / "reports"
    reports.mkdir()
    output_root = tmp_path / "output"
    runs = tmp_path / "runs"
    runs.mkdir()
    return reports, output_root, runs


def test_no_sidecar_never_scanned(tmp_path):
    """An output directory with canaries.json and hosts.yml but no sidecar is not in discover."""
    reports, output_root, runs = _layout(tmp_path)
    _output_dir(output_root, "ws1")
    assert canary_watch.discover(str(reports), str(output_root), str(runs)) == []


def test_newest_sidecar_wins(tmp_path):
    """Two sidecars naming one instance (deleted and recreated under the same name): the newer only."""
    reports, output_root, runs = _layout(tmp_path)
    _output_dir(output_root, "ws1")
    old = _sidecar(reports, WS1, "ws1", owner="old-owner")
    new = _sidecar(reports, WS2, "ws1", owner="new-owner")
    now = time.time()
    os.utime(old, (now - 100, now - 100))
    os.utime(new, (now, now))
    result = canary_watch.discover(str(reports), str(output_root), str(runs))
    assert [w.id for w in result] == [WS2]
    assert [w.owner for w in result] == ["new-owner"]


def test_running_until_archived(tmp_path):
    """running while hosts.yml is newer than every runs_dir/*_<instance> directory; an archive dir
    newer than hosts.yml makes it not running. A run dir for a different instance does not match
    (exact suffix, not a prefix of it: ws1 must not match x_ws10)."""
    reports, output_root, runs = _layout(tmp_path)
    directory = _output_dir(output_root, "ws1")
    _sidecar(reports, WS1, "ws1")
    [w] = canary_watch.discover(str(reports), str(output_root), str(runs))
    assert w.running is True
    assert w.instance == "ws1"
    assert w.output_dir == str(directory)
    assert w.api_host == "api.spe.test"
    assert w.ssh.user == "ubuntu" and w.ssh.host == "localhost"
    assert w.encrypted is False

    unrelated = runs / "20261110T000000_x_ws10"  # must not match instance "ws1"
    unrelated.mkdir()
    [w] = canary_watch.discover(str(reports), str(output_root), str(runs))
    assert w.running is True

    archived = runs / "20261110T010000_ws1"
    archived.mkdir()
    now = time.time()
    os.utime(archived, (now + 1000, now + 1000))  # newer than hosts.yml
    [w] = canary_watch.discover(str(reports), str(output_root), str(runs))
    assert w.running is False


def test_encrypted_record(tmp_path):
    """A workspace whose record is only canaries.json.age is still returned, flagged encrypted."""
    reports, output_root, runs = _layout(tmp_path)
    _output_dir(output_root, "ws1", encrypted=True)
    _sidecar(reports, WS1, "ws1")
    [w] = canary_watch.discover(str(reports), str(output_root), str(runs))
    assert w.encrypted is True


def test_neither_record_file_is_skipped(tmp_path):
    """Neither canaries.json nor canaries.json.age: the workspace is skipped entirely."""
    reports, output_root, runs = _layout(tmp_path)
    _output_dir(output_root, "ws1", no_record=True)
    _sidecar(reports, WS1, "ws1")
    assert canary_watch.discover(str(reports), str(output_root), str(runs)) == []


def test_generation_changes_with_hosts_yml(tmp_path):
    """generation is a SHA-256 of hosts.yml's bytes and mtime: a rewrite with the same bytes but a
    later mtime, and a rewrite with different bytes, both start a new generation."""
    reports, output_root, runs = _layout(tmp_path)
    directory = _output_dir(output_root, "ws1")
    _sidecar(reports, WS1, "ws1")
    hosts_path = directory / "hosts.yml"

    [w1] = canary_watch.discover(str(reports), str(output_root), str(runs))
    data = hosts_path.read_bytes()
    now = time.time()
    os.utime(hosts_path, (now + 10, now + 10))  # same bytes, later mtime
    [w2] = canary_watch.discover(str(reports), str(output_root), str(runs))
    assert hosts_path.read_bytes() == data
    assert w1.generation != w2.generation

    hosts_path.write_text(hosts_path.read_text() + "extra: value\n")  # different bytes
    os.utime(hosts_path, (now + 20, now + 20))
    [w3] = canary_watch.discover(str(reports), str(output_root), str(runs))
    assert w3.generation != w2.generation


def test_bad_or_unmatched_sidecars_are_skipped(tmp_path):
    """A sidecar that is not valid JSON, lacks `instance`, or whose filename is not a UUID: never
    raises out of discover, just skipped. A sidecar naming an instance with no hosts.yml at all is
    skipped too."""
    reports, output_root, runs = _layout(tmp_path)
    _output_dir(output_root, "ws1")
    _sidecar(reports, WS1, "ws1")
    (reports / "not-a-uuid.json").write_text(json.dumps({"instance": "ws1", "owner": "mallory"}))
    (reports / f"{WS2}.json").write_text("{not json")
    third = reports / "33333333-3333-3333-3333-333333333333.json"
    third.write_text(json.dumps({"owner": "eve"}))  # no "instance"
    fourth = reports / "44444444-4444-4444-4444-444444444444.json"
    fourth.write_text(json.dumps({"instance": "no-such-instance", "owner": "eve"}))
    [w] = canary_watch.discover(str(reports), str(output_root), str(runs))
    assert w.instance == "ws1"
