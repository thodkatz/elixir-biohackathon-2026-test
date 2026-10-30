#!/usr/bin/env python3
"""Drive the chat UI's session sidebar in a real browser, against the scripted agent (no LLM).

    python3 platform/dev/e2e/sessions.py [--shots DIR] [--sessions DIR]

Run `npm ci && npm run build` in platform/agui/copilotkit-chat first. The script starts
platform/dev/fake_agent.py (with uv, in platform/agui/pydantic-ai-agent) and the standalone chat UI
with its own sessions directory, walks the sidebar (list, open, New chat, ?session=) and
checks the session files after each step. Needs Python Playwright with Chromium (`pip install playwright` and
`playwright install chromium`). Exits nonzero on the first failed check.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "platform" / "agui" / "copilotkit-chat"
AGENT_DIR = ROOT / "platform" / "agui" / "pydantic-ai-agent"
KEY = "e2e-sessions-key"
AGENT_PORT = 18108
UI_PORT = 3108
BASE = f"http://127.0.0.1:{UI_PORT}"
XSS = '<img src=x onerror="window.__speXss=1">'


def wait_http(url: str, what: str, seconds: float = 60) -> None:
    until = time.time() + seconds
    while time.time() < until:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except Exception:
            time.sleep(0.25)
    sys.exit(f"FAIL: {what} did not come up at {url}")


class Run:
    def __init__(self, page: Page, sessions: Path, shots: Path | None):
        self.page, self.sessions, self.shots, self.n = page, sessions, shots, 0

    def shot(self, name: str) -> None:
        if self.shots:
            self.n += 1
            self.page.screenshot(path=str(self.shots / f"{self.n:02d}-{name}.png"), full_page=True)

    def ok(self, what: str) -> None:
        print(f"ok - {what}", flush=True)

    def files(self) -> dict[str, dict]:
        return {p.stem: json.loads(p.read_text()) for p in self.sessions.glob("*.json")}

    def wait_runs(self, sid: str, n: int, seconds: float = 5) -> dict:
        """The session's record once it has n runs: the recorder writes after the answer is shown."""
        until = time.time() + seconds
        while True:
            path = self.sessions / f"{sid}.json"
            rec = json.loads(path.read_text()) if path.exists() else {"runs": []}
            if len(rec["runs"]) >= n or time.time() > until:
                assert len(rec["runs"]) == n, (sid, n, rec["runs"])
                return rec
            time.sleep(0.2)

    def url_session(self) -> str | None:
        from urllib.parse import parse_qs, urlparse
        return (parse_qs(urlparse(self.page.url).query).get("session") or [None])[0]

    def rows(self):
        return self.page.locator(".spe-sidebar .spe-row")

    def row(self, title: str):
        return self.rows().filter(has=self.page.locator(".spe-row-title", has_text=title))

    def send(self, text: str, turn: int) -> None:
        box = self.page.get_by_test_id("copilot-chat-textarea")
        box.fill(text)
        box.press("Enter")
        expect(self.page.get_by_text(f"Turn {turn}: the command ran.")).to_be_visible(timeout=20_000)

    def menu(self, title: str, item: str) -> None:
        self.row(title).locator(".spe-row-menu").click()
        self.page.get_by_role("menuitem", name=item).click()


def check_list(r: Run) -> dict[str, str]:
    page = r.page
    page.goto(BASE + "/")
    expect(page.get_by_role("button", name="New chat")).to_be_visible()
    assert r.url_session() is None, page.url
    r.ok("first load: no session in the URL, New chat shown")

    r.send("List the home directory", 1)
    expect(r.row("List the home directory")).to_have_count(1, timeout=5_000)
    first = r.url_session()
    assert first and first in r.files(), (first, list(r.files()))
    rec = r.files()[first]
    assert [x["status"] for x in rec["runs"]] == ["completed"] and rec["title"] == "List the home directory"
    r.ok("first run: the row appears, the URL names the session, the file has one completed run")

    page.reload()
    expect(page.get_by_text("Turn 1: the command ran.")).to_be_visible(timeout=10_000)
    expect(page.locator(".spe-tool .spe-tool-name", has_text="run_command")).to_have_count(1)
    expect(r.row("List the home directory")).to_have_class("spe-row spe-row-active")
    r.ok("reload reopens the session with its tool card")

    page.get_by_role("button", name="New chat").click()
    expect(page.get_by_text("Turn 1: the command ran.")).to_have_count(0)
    assert r.url_session() is None, page.url
    r.send("Read the dataset", 1)
    expect(r.row("Read the dataset")).to_have_count(1, timeout=5_000)
    second = r.url_session()
    assert second and second != first
    r.ok("New chat: empty history, a second session after its first run")

    page.get_by_role("button", name="New chat").click()
    r.send(XSS, 1)
    expect(r.rows()).to_have_count(3, timeout=5_000)
    third = r.url_session()
    assert third and r.files()[third]["title"] == XSS
    expect(r.row("<img src=x")).to_have_count(1)
    assert page.evaluate("window.__speXss") is None
    r.ok("a title of an HTML tag shows as literal text and runs nothing")
    r.shot("three-sessions")

    r.row("List the home directory").locator(".spe-row-open").click()
    # "Turn 1" text is already on screen from the previous session, so waiting on it races
    # open(): wait for the URL to actually name `first` before asserting on it.
    page.wait_for_url(f"**session={first}**")
    expect(page.get_by_text("Turn 1: the command ran.")).to_be_visible(timeout=10_000)
    assert r.url_session() == first
    r.send("And the hidden files?", 2)
    assert [x["status"] for x in r.wait_runs(first, 2)["runs"]] == ["completed", "completed"]
    r.ok("opening a row restores its history, and a run continues it")

    for bad in ("not-a-uuid", str(uuid.uuid4()), first.upper()):
        page.goto(f"{BASE}/?session={bad}")
        expect(page.get_by_role("button", name="New chat")).to_be_visible()
        expect(page.get_by_test_id("copilot-chat-textarea")).to_be_visible(timeout=10_000)
        expect(page.locator(".spe-error")).to_have_count(0)
        assert r.url_session() is None, page.url
    r.ok("?session= malformed, unknown or upper-case: new session, parameter dropped, no error bar")
    return {"first": first, "second": second, "third": third}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shots", type=Path, help="write numbered screenshots here")
    ap.add_argument("--sessions", type=Path, help="sessions directory to use and keep (default: a temporary one)")
    args = ap.parse_args()
    standalone = APP / ".next" / "standalone"
    if not (standalone / "server.js").exists():
        sys.exit("FAIL: run `npm ci && npm run build` in platform/agui/copilotkit-chat first")
    shutil.copytree(APP / ".next" / "static", standalone / ".next" / "static", dirs_exist_ok=True)
    data = args.sessions or Path(tempfile.mkdtemp(prefix="spe-e2e-")) / "sessions"
    data.mkdir(parents=True, exist_ok=True)
    if args.shots:
        args.shots.mkdir(parents=True, exist_ok=True)
    procs = [subprocess.Popen(["uv", "run", "--group", "dev", "python", "../../dev/fake_agent.py",
                               "--port", str(AGENT_PORT), "--key", KEY], cwd=AGENT_DIR)]
    try:
        wait_http(f"http://127.0.0.1:{AGENT_PORT}/healthz", "the fake agent")
        env = {**os.environ, "AGENT_URL": f"http://127.0.0.1:{AGENT_PORT}/agent", "AGENT_API_KEY": KEY,
               "PORT": str(UI_PORT), "HOSTNAME": "127.0.0.1", "SPE_SESSIONS_DIR": str(data),
               "NEXT_MANUAL_SIG_HANDLE": "true"}
        procs.append(subprocess.Popen(["node", "server.js"], cwd=standalone, env=env))
        wait_http(BASE + "/api/sessions", "the chat UI")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            r = Run(page, data, args.shots)
            check_list(r)
            browser.close()
        print(f"sessions: {data}")
    finally:
        for proc in reversed(procs):
            proc.terminate()
            proc.wait(timeout=35)


if __name__ == "__main__":
    main()
