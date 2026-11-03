"""write_run.py renders an AG-UI bundle (the chat UI's exporter): run status, ignored content, compaction, the
AG-UI index; a title or message cannot forge the run directory's Markdown; an Open WebUI bundle renders
byte-identically to before. The AG-UI bundles are the committed exports of the fixture journals."""
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
WRITE_RUN = TESTS.parents[1] / "ansible" / "roles" / "run_archive" / "files" / "write_run.py"
RECORD = TESTS / "fixtures" / "agui-record"
OWUI = TESTS / "fixtures" / "openwebui-run"

TOOLS, IGNORED, STATUSES, BRANCHES, MARKUP = (f"00000000-0000-4000-8000-00000000000{n}" for n in range(1, 6))
NAMES = {
    TOOLS: "01-list-the-home-directory",
    IGNORED: "02-hello",
    STATUSES: "03-run-a-slow-command",
    BRANCHES: "04-first-question",
    MARKUP: "05-try-the-pipe-forged-heading-script-alert-1-script",
}


def load():
    spec = importlib.util.spec_from_file_location("write_run", WRITE_RUN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wr = load()


def run(bundle, out):
    return subprocess.run([sys.executable, str(WRITE_RUN), str(bundle), str(out), "Run report"],
                          capture_output=True, text=True, check=True)


def tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def outside_fences(md):
    """The lines a Markdown viewer would not show as code."""
    out, ticks = [], None
    for line in md.splitlines():
        if ticks is None:
            m = re.match(r"(`{3,})", line)
            if m:
                ticks = m.group(1)
            else:
                out.append(line)
        elif re.fullmatch(f"`{{{len(ticks)},}}\\s*", line):
            ticks = None
    return out


def prepare(tmp_path, bundle="live.bundle.json", journals=True, log=True):
    """A run directory as tasks/write.yml leaves it before write_run.py runs: the raw journals and the run log."""
    out = tmp_path / "run"
    out.mkdir()
    if journals:
        (out / "agui-journals").mkdir()
        for p in RECORD.glob("*.jsonl"):
            shutil.copyfile(p, out / "agui-journals" / p.name)
    if log:
        (out / "agent-runs.jsonl").write_text('{"run_id": "r1-1"}\n{"run_id": "r1-2"}\n')
    src = tmp_path / "bundle.json"
    shutil.copyfile(RECORD / bundle, src)
    return src, out


@pytest.fixture
def rendered(tmp_path):
    src, out = prepare(tmp_path)
    proc = run(src, out)
    assert "5 sessions (1 hidden, 1 deleted), live archive, run log" in proc.stdout
    return out


def chat(out, sid):
    return (out / "chats" / f"{NAMES[sid]}.md").read_text()


def test_openwebui_bundle_renders_byte_identically(tmp_path):
    """The expected tree was written by write_run.py before it learnt AG-UI bundles."""
    out = tmp_path / "expected"
    run(OWUI / "bundle.json", out)
    assert tree(out) == tree(OWUI / "expected")
