"""wes_guard.py: WES writes carry no attachment and only TRS URIs of the stack's TRS."""
import http.client
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ansible_render import ANSIBLE

TRS = "trs://trs-filer.weskit.internal:8080/wes-drs-smoke/1.0/NFL/main.nf"


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("wes_guard", ANSIBLE / "roles/workflow_stack/files/wes_guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def multipart(fields, files=()):
    b = "b0undary"
    out = "".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in fields.items())
    out += "".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{n}"\r\n'
                   f"Content-Type: text/plain\r\n\r\n{c}\r\n" for k, n, c in files)
    return f"multipart/form-data; boundary={b}", (out + f"--{b}--\r\n").encode()


def test_trs_run_passes(guard):
    assert guard.check(*multipart({"workflow_url": TRS, "workflow_type": "NFL"})) is None


@pytest.mark.parametrize("files", [[("workflow_attachment", "nextflow.config", "x")],
                                   [("other", "a.txt", "x")]])
def test_any_file_part_is_refused(guard, files):
    status, reason = guard.check(*multipart({"workflow_url": TRS}, files))
    assert status == 403 and "attachment" in reason


@pytest.mark.parametrize("url", ["main.nf", "file:main.nf", "https://evil.example/m.nf",
                                 "trs://other.host:8080/t/1/NFL/main.nf", TRS + "?x=1"])
def test_non_trs_urls_are_refused(guard, url):
    assert guard.check(*multipart({"workflow_url": url}))[0] == 403
    assert guard.check("application/json", json.dumps({"workflow_url": url}).encode())[0] == 403
    assert guard.check("application/x-www-form-urlencoded", f"workflow_url={url}".encode())[0] == 403


def test_malformed_and_unknown_bodies_fail_closed(guard):
    assert guard.check("multipart/form-data", b"--x\r\nno boundary")[0] == 400
    assert guard.check("application/json", b"{not json")[0] == 400
    assert guard.check("text/plain", b"workflow_url=main.nf")[0] == 415
    assert guard.check("", b"") is None  # POST /runs/ID/cancel has no body


def test_proxy_forwards_allowed_and_blocks_refused(guard):
    seen = []

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append((self.path, self.rfile.read(int(self.headers["Content-Length"] or 0))))
            body = b'{"run_id": "r1"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    gs = guard.serve("127.0.0.1", 0, "127.0.0.1", up.server_address[1])
    for s in (up, gs):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        def post(ctype, body):
            c = http.client.HTTPConnection("127.0.0.1", gs.server_address[1], timeout=10)
            c.request("POST", "/ga4gh/wes/v1/runs", body=body, headers={"Content-Type": ctype})
            r = c.getresponse()
            return r.status, json.loads(r.read())
        assert post(*multipart({"workflow_url": TRS})) == (200, {"run_id": "r1"})
        status, body = post(*multipart({"workflow_url": "main.nf"}))
        assert status == 403 and body["status_code"] == 403
        assert len(seen) == 1 and seen[0][0] == "/ga4gh/wes/v1/runs"
    finally:
        gs.shutdown()
        up.shutdown()
