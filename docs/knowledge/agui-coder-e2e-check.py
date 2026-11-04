"""End-to-end check of the AG-UI chat in a Coder workspace, through `coder port-forward` on :13000
(docs/knowledge/agui-coder-e2e-check.md). Paid model calls: a few dozen.

Usage: SPE_WS=theo/agui-e2e python3 agui-coder-e2e-check.py <out dir> [--turns N] [--compactions N]

Two tabs: sessions run side by side, the other tab switches into a session mid-run, stop and send again at
once, new / rename / delete, long conversations until each has --compactions compactions (lower the agent's
`context_window_tokens` first), `/compact` with and without a focus, then reload and reopen every session and
compare the chat with its journal. Writes <out dir>/journals.json (the summaries) for the archive comparison.
"""
import argparse, json, os, re, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "platform" / "dev" / "e2e"))
from sessions import read_journal, summary  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402

URL = "http://127.0.0.1:13000/"
WS = os.environ.get("SPE_WS", "theo/agui-e2e")
ap = argparse.ArgumentParser()
ap.add_argument("out")
ap.add_argument("--turns", type=int, default=14)
ap.add_argument("--compactions", type=int, default=2)
args = ap.parse_args()
OUT = Path(args.out); OUT.mkdir(parents=True, exist_ok=True)
results = []


def ok(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f" — {detail}" if detail else ""), flush=True)


def vm(cmd):
    return subprocess.run(["coder", "ssh", WS, "--", cmd], capture_output=True, text=True).stdout


def journals():
    script = ("const fs=require('fs');const d='/data/sessions';const o={};"
              "for(const f of fs.readdirSync(d))if(f.endsWith('.jsonl'))o[f.slice(0,-6)]=fs.readFileSync(d+'/'+f,'utf8');"
              "process.stdout.write(JSON.stringify(o))")
    out = vm(f"cd ~/spe-frontend && docker compose exec -T chat-ui node -e \"{script}\"")
    return {sid: summary(read_journal(text)) for sid, text in json.loads(out or "{}").items()}


def done_runs(sid):
    rec = journals().get(sid)
    return [r for r in rec["runs"] if r["status"] != "incomplete"] if rec else []


def session_of(page, seconds=30):
    t0 = time.time()
    while time.time() - t0 < seconds:
        m = re.search(r"[?&]session=([^&]+)", page.url)
        if m:
            return m.group(1)
        page.wait_for_timeout(500)
    return None


def errors(page):
    return [t for t in page.locator(".spe-error").all_inner_texts() if t.strip()]


def submit(page, text):
    box = page.get_by_test_id("copilot-chat-textarea")
    box.fill(text)
    box.press("Enter")


def wait_done(page, sid, before, timeout=900):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if len(done_runs(sid)) > before:
            expect(page.get_by_role("button", name="New chat")).to_be_enabled(timeout=60_000)
            page.wait_for_timeout(1000)
            return True
        time.sleep(5)
    return False


def send(page, text, timeout=900):
    """Send in the page's session (a new one if none yet); True when its journal has the run ended."""
    sid = session_of(page, 0.1)
    before = len(done_runs(sid)) if sid else 0
    submit(page, text)
    sid = sid or session_of(page)
    return sid, wait_done(page, sid, before, timeout)


def open_session(page, sid):
    page.goto(URL + f"?session={sid}")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)


def row(page, title):
    return page.locator(".spe-sidebar .spe-row").filter(has=page.locator(".spe-row-title", has_text=title))


with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1400, "height": 900})
    A, B = ctx.new_page(), ctx.new_page()
    perr = []
    for pg in (A, B):
        pg.on("pageerror", lambda e: perr.append(str(e)))
        pg.goto(URL); pg.wait_for_load_state("networkidle")

    # 1. two sessions at once; tab B switches into A's session while A's run streams
    A.get_by_role("button", name="New chat").click()
    submit(A, "List the files in the dataset directory, then count the lines of the two largest text files.")
    sA = session_of(A)
    B.get_by_role("button", name="New chat").click()
    sB, okB = send(B, "In two sentences: what does a GA4GH WES service do?")
    ok("two sessions at once: B's run ended while A's ran", okB and sA != sB, f"A={sA} B={sB}")
    still = [r["status"] for r in journals()[sA]["runs"]] == ["incomplete"]
    B.goto(URL); B.wait_for_load_state("networkidle")
    open_session(B, sA)
    B.screenshot(path=str(OUT / "1-switch-mid-run.png"), full_page=True)
    ok("tab B opened A's session" + (" mid-run" if still else " (A had already ended)"),
       session_of(B, 2) == sA and not errors(B), "; ".join(errors(B)))
    ok("A's run ended", wait_done(A, sA, 0))
    open_session(B, sA)
    ok("B shows A's whole run after it ended", B.locator(".copilotKitUserMessage").count() == 1)

    # 2. stop mid-run and send again at once
    before = len(done_runs(sA))
    submit(A, "Run `sleep 30` in the sandbox, then list /data-share and summarise what is there.")
    expect(A.get_by_role("button", name="New chat")).to_be_disabled(timeout=10_000)
    A.wait_for_timeout(4000)
    A.get_by_test_id("copilot-send-button").click()  # stop
    expect(A.get_by_role("button", name="New chat")).to_be_enabled(timeout=30_000)
    submit(A, "Say OK and nothing else.")
    A.wait_for_timeout(3000)
    errs = errors(A)
    ok("stop then send at once: no 'Thread already running'", not any("already running" in e for e in errs), "; ".join(errs))
    ok("resent run ended", wait_done(A, sA, before + 1))
    st = [r["status"] for r in journals()[sA]["runs"]]
    ok("journal: cancelled then completed", st[-2:] == ["cancelled", "completed"], str(st))

    # 3. new, rename, delete
    B.goto(URL); B.wait_for_load_state("networkidle")
    B.get_by_role("button", name="New chat").click()
    sC, okC = send(B, "Say hi in three words.")
    B.wait_for_timeout(3000)
    ok("third session ran", okC)
    B.get_by_role("button", name="Chat actions").click()
    B.get_by_role("menuitem", name="Rename").click()
    B.get_by_label("Chat title").fill("E2E long C"); B.get_by_label("Chat title").press("Enter")
    expect(row(B, "E2E long C")).to_have_count(1, timeout=10_000)
    ok("rename kept in the journal", journals()[sC]["title"] == "E2E long C", journals()[sC]["title"])
    B.get_by_role("button", name="New chat").click()
    sD, okD = send(B, "Say bye in three words.")
    B.wait_for_timeout(3000)
    title_d = journals()[sD]["title"]
    row(B, title_d).first.locator(".spe-row-menu").click()
    B.get_by_role("menuitem", name="Delete").click()
    B.get_by_role("alertdialog").get_by_role("button", name="Delete").click()
    expect(row(B, title_d)).to_have_count(0, timeout=10_000)
    ok("delete: row gone, journal kept with deleted_at", journals()[sD]["deleted_at"] is not None)

    # 4. long conversations in A and C: several compactions each, /compact with and without a focus
    for page, sid, cmd in ((A, sA, "/compact"), (B, sC, "/compact keep the line counts and file names")):
        open_session(page, sid)
        _, okc = send(page, cmd)
        ok(f"{cmd!r} in {sid[:8]} ran", okc and page.locator(".spe-compaction").count() >= 1,
           f"dividers={page.locator('.spe-compaction').count()}")
        turn = 0
        while page.locator(".spe-compaction").count() < args.compactions + 1 and turn < args.turns:
            turn += 1
            _, okt = send(page, f"Turn {turn}: run `seq 1 3000` exactly as written, without pipes, filters or "
                                "redirection, then read its whole output and tell me only the last line it printed.")
            if not okt:
                ok(f"turn {turn} in {sid[:8]} ended", False); break
            if errors(page):
                ok(f"turn {turn} in {sid[:8]}: no error in the chat", False, "; ".join(errors(page))); break
        n = page.locator(".spe-compaction").count()
        ok(f"{sid[:8]}: {n} compactions after {turn} turns", n >= args.compactions + 1)
        page.screenshot(path=str(OUT / f"4-long-{sid[:8]}.png"), full_page=True)

    # 5. reload and reopen each session: the chat agrees with its journal
    rec = journals()
    for sid in (sA, sB, sC):
        open_session(A, sid)
        users = [m for r in rec[sid]["runs"] for m in r["messages"] if m["role"] == "user"]
        shown = A.locator(".copilotKitUserMessage").count()
        ok(f"reopened {sid[:8]}: user messages shown = journaled", shown == len(users), f"{shown} vs {len(users)}")
        ok(f"reopened {sid[:8]}: no error", not errors(A), "; ".join(errors(A)))
    A.screenshot(path=str(OUT / "5-reopened.png"), full_page=True)
    ok("no page errors", not perr, "; ".join(perr)[:300])
    (OUT / "journals.json").write_text(json.dumps(rec, indent=1))
    (OUT / "ids.json").write_text(json.dumps({"A": sA, "B": sB, "C": sC, "D": sD}))
    b.close()

print(f"\n{sum(r[1] for r in results)}/{len(results)} passed")
