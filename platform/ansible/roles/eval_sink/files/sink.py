"""The ladder's test receiver: logs every request as one JSON line and answers 200. Standard library only.

It stands for a host outside the SPE (spec part 04, *The test receiver*). Evaluation only: never in a deployment
that holds real data.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

MAX_BODY = 1 << 20


def make_server(address, log: Path) -> ThreadingHTTPServer:
    # The log exists, empty, from the start: the evaluation reads a missing log as "no receiver"
    # (isolation.SINK_LOG) and an empty one as "a receiver, no requests yet".
    Path(log).touch()
    lock = Lock()

    class Handler(BaseHTTPRequestHandler):
        def _any(self):
            length = min(int(self.headers.get("Content-Length") or 0), MAX_BODY)
            body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
            line = json.dumps({"method": self.command, "host": self.headers.get("Host", ""), "path": self.path,
                               "body": body}, ensure_ascii=False)
            with lock, open(log, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
            self.send_response(200)
            self.send_header("Content-Length", "3")
            self.end_headers()
            self.wfile.write(b"ok\n")

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _any

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer(address, Handler)


if __name__ == "__main__":
    make_server(("0.0.0.0", 8099), Path(sys.argv[1] if len(sys.argv) > 1 else "/log/requests.jsonl")).serve_forever()
