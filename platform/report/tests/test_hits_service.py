"""The participant hits page and hits.json (spec *Participant page*, *Security*; decisions 6, 10,
11): who may see a workspace's hits (`Handler.can_see_hits`), the page and its JSON twin served
from the hits directory (slice 2's watcher), against a fake Coder API like test_report.py's.
Fixtures use made-up tokens only (FCANARY-TEST01, from fixtures/canary/canaries.json)."""
from __future__ import annotations

import json
import re
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import canary_hits  # noqa: E402
import canary_record  # noqa: E402
import hits_view  # noqa: E402
import sperange_report as sr  # noqa: E402
from canary_hits import HitsFile  # noqa: E402

WID = "11111111-2222-4333-8444-555555555555"
OTHER = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
NOSIDECAR = "99999999-aaaa-4bbb-8ccc-dddddddddddd"
USERS = {
    "tok-anna": {"username": "anna", "email": "anna@example.org", "roles": [{"name": "member"}]},
    "tok-bob": {"username": "bob", "email": "bob@example.org", "roles": []},
    "tok-root": {"username": "admin", "email": "admin@example.org", "roles": [{"name": "owner"}]},
}

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "canary"
CANARIES = canary_record.load_canaries(FIXTURES)
API_HOST = canary_record.read_hosts(FIXTURES)["api_host"]
HOSTILE = "<img src=x onerror=alert(1)>"


def _agui_hit() -> dict:
    """One AG-UI journal hit (slice 1's fixtures.canary/agui-journals/s1.jsonl), kind touched:
    the flag file's content read back by a tool."""
    reader = canary_hits.JournalReader("s1")
    lines = [json.loads(line) for line in (FIXTURES / "agui-journals" / "s1.jsonl").read_text().splitlines()
             if line.strip()]
    places = [p for line in lines for p in reader.feed(line)]
    hits = [h for p in places for h in canary_hits.hits_for(p, CANARIES, API_HOST)]
    return next(h for h in hits if h["kind"] == "touched")


def _openwebui_hit() -> dict:
    """One Open WebUI hit (slice 1's fixtures/canary/openwebui-export.json), kind touched."""
    export = json.loads((FIXTURES / "openwebui-export.json").read_text())
    places = [p for chat in export["chats"] for p in canary_hits.openwebui_places(chat, "archive")]
    hits = [h for p in places for h in canary_hits.hits_for(p, CANARIES, API_HOST)]
    return next(h for h in hits if h["kind"] == "touched")


def _record(wid: str, partial: dict) -> dict:
    return {"detected": "2026-11-10T14:03:30Z", "workspace": wid, "instance": "cw-anna-tm-test",
            "owner": "anna", **partial}


class FakeCoder(BaseHTTPRequestHandler):
    def do_GET(self):
        tok = self.headers.get("Coder-Session-Token", "")
        user = USERS.get(tok)
        if self.path == "/api/v2/users/me":
            if user is None:
                return self.reply(401, {"message": "no"})
            return self.reply(200, user)
        self.reply(404, {"message": "?"})

    def reply(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def coder():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeCoder)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture
def service(tmp_path, coder):
    reports_dir, hits_dir = tmp_path / "reports", tmp_path / "hits"
    reports_dir.mkdir()
    hits_dir.mkdir()
    (reports_dir / f"{WID}.json").write_text(json.dumps(
        {"owner": "anna", "owner_email": "anna@example.org", "workspace": "tm-test",
         "instance": "cw-anna-tm-test", "created": "2026-11-06 15:00 UTC"}))
    srv = sr.make_server("127.0.0.1:0", str(reports_dir), coder, str(hits_dir))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", hits_dir
    srv.shutdown()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def call(base, path, token=None):
    headers = {"Cookie": f"{sr.COOKIE}={token}"} if token else {}
    req = urllib.request.Request(base + path, headers=headers)
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def write_hits(hits_dir: Path, wid: str, records: list[dict]) -> None:
    hf = HitsFile(str(hits_dir / f"{wid}.jsonl"))
    for record in records:
        hf.append(dict(record))


def write_status(hits_dir: Path, wid: str, status: dict) -> None:
    (hits_dir / f"{wid}.status.json").write_text(json.dumps(status))


# --- the page -----------------------------------------------------------------------------------

def test_owner_sees_both_frontends_with_value(service):
    base, hits_dir = service
    write_hits(hits_dir, WID, [_record(WID, _agui_hit()), _record(WID, _openwebui_hit())])
    status, _, body = call(base, f"/reports/{WID}/hits", token="tok-anna")
    assert status == 200
    text = body.decode()
    assert "AG-UI" in text and "Open WebUI" in text
    assert "FCANARY-TEST01" in text


def test_admin_sees_any_workspace(service):
    base, hits_dir = service
    write_hits(hits_dir, NOSIDECAR, [_record(NOSIDECAR, _agui_hit())])
    status, _, body = call(base, f"/reports/{NOSIDECAR}/hits", token="tok-root")
    assert status == 200
    assert "FCANARY-TEST01" in body.decode()


def test_other_user_gets_403(service):
    base, hits_dir = service
    write_hits(hits_dir, WID, [_record(WID, _agui_hit())])
    assert call(base, f"/reports/{WID}/hits", token="tok-bob")[0] == 403
    assert call(base, f"/reports/{WID}/hits.json", token="tok-bob")[0] == 403


def test_logged_out_redirect_and_401(service):
    base, _ = service
    status, headers, _ = call(base, f"/reports/{WID}/hits")
    assert status == 302
    assert headers["Location"] == f"/login?redirect=%2Freports%2F{WID}"
    assert call(base, f"/reports/{WID}/hits.json")[0] == 401


def test_notice_on_page(service):
    base, hits_dir = service
    write_hits(hits_dir, WID, [])
    status, _, body = call(base, f"/reports/{WID}/hits", token="tok-anna")
    assert status == 200
    assert hits_view.NOTICE in body.decode()


def test_stopped_workspace_renders(service):
    base, hits_dir = service
    write_hits(hits_dir, WID, [_record(WID, _agui_hit())])
    write_status(hits_dir, WID, {"state": "stopped", "since": "2026-11-10T14:05:00Z",
                                 "last_poll": "2026-11-10T14:04:00Z"})
    status, _, body = call(base, f"/reports/{WID}/hits", token="tok-anna")
    assert status == 200
    text = body.decode()
    assert "stopped" in text
    assert "FCANARY-TEST01" in text


def test_stopped_with_archive_incomplete_note(service):
    base, hits_dir = service
    write_status(hits_dir, WID, {"state": "stopped", "since": "2026-11-10T14:05:00Z",
                                 "note": "archive incomplete"})
    status, _, body = call(base, f"/reports/{WID}/hits", token="tok-anna")
    assert status == 200
    assert "stopped · archive incomplete" in body.decode()


def test_no_hits_file_yet(service):
    base, hits_dir = service
    write_status(hits_dir, WID, {"state": "running", "last_poll": "2026-11-10T14:03:00Z"})
    status, _, body = call(base, f"/reports/{WID}/hits", token="tok-anna")
    assert status == 200
    assert "No hits yet." in body.decode()


def test_encrypted_record_says_so(service):
    base, hits_dir = service
    write_status(hits_dir, WID, {"state": "encrypted", "note": "canary record is encrypted"})
    status, _, body = call(base, f"/reports/{WID}/hits", token="tok-anna")
    assert status == 200
    assert "The canary record is encrypted: the watcher cannot match this workspace." in body.decode()


def test_not_watched_without_a_status_file(service):
    base, _ = service
    status, _, body = call(base, f"/reports/{WID}/hits", token="tok-anna")
    assert status == 200
    assert "Not watched yet." in body.decode()


def test_malformed_id_is_404(service):
    base, _ = service
    assert call(base, "/reports/not-a-uuid/hits", token="tok-anna")[0] == 404
    assert call(base, "/reports/not-a-uuid/hits.json", token="tok-anna")[0] == 404


# --- hits.json ------------------------------------------------------------------------------------

def test_hits_json_after(service):
    base, hits_dir = service
    write_hits(hits_dir, WID, [_record(WID, _agui_hit()), _record(WID, _openwebui_hit())])
    status, _, body = call(base, f"/reports/{WID}/hits.json", token="tok-anna")
    assert status == 200
    data = json.loads(body)
    assert data["workspace"] == WID
    assert len(data["hits"]) == 2
    status, _, body = call(base, f"/reports/{WID}/hits.json?after=1", token="tok-anna")
    after = json.loads(body)
    assert len(after["hits"]) == 1
    assert after["hits"][0]["id"] == 2
    assert call(base, f"/reports/{WID}/hits.json?after=x", token="tok-anna")[0] == 400


def test_hits_json_ignores_other_query_keys(service):
    base, hits_dir = service
    write_hits(hits_dir, WID, [_record(WID, _agui_hit())])
    status, _, _ = call(base, f"/reports/{WID}/hits.json?foo=bar", token="tok-anna")
    assert status == 200


def test_hits_json_status_null_without_a_status_file(service):
    base, hits_dir = service
    write_hits(hits_dir, WID, [_record(WID, _agui_hit())])
    data = json.loads(call(base, f"/reports/{WID}/hits.json", token="tok-anna")[2])
    assert data["status"] is None


# --- Review Focus 1: hostile output ---------------------------------------------------------------

def test_page_escapes_titles_and_excerpts(service):
    base, hits_dir = service
    hit = _record(WID, _agui_hit() | {
        "session": {"id": "s1", "title": HOSTILE},
        "excerpt": {"text": f"{HOSTILE} FCANARY-TEST01", "start": len(HOSTILE) + 1,
                    "end": len(HOSTILE) + 1 + len("FCANARY-TEST01")},
    })
    write_hits(hits_dir, WID, [hit])
    status, _, body = call(base, f"/reports/{WID}/hits", token="tok-anna")
    text = body.decode()
    assert status == 200
    assert "<img" not in text
    assert "&lt;img src=x onerror=alert(1)&gt;" in text
    assert "<mark>FCANARY-TEST01</mark>" in text


def test_csp_and_no_inline_script(service):
    base, hits_dir = service
    write_hits(hits_dir, WID, [_record(WID, _agui_hit())])
    status, headers, body = call(base, f"/reports/{WID}/hits", token="tok-anna")
    assert status == 200
    assert "Content-Security-Policy" in headers
    text = body.decode()
    assert "<script>" not in text
    for tag in re.findall(r"<script\b[^>]*>", text):
        assert "src=" in tag
