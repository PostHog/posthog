"""Source of the in-sandbox DataV2 kernel-server.

This is NOT imported by Django — the string below is written into the notebook
sandbox and launched there (stdlib-only, no third-party deps). It mirrors PostHog
Code's agent-server: a long-running HTTP server the backend POSTs a run to with a
single request, instead of transferring a script per run.

`POST /run` accepts {run_id, code, callback_url, callback_token}, returns 202
immediately, and does the work + result callback on a background thread. For the
Journey 1 slice it fabricates the result (42); a later version runs `code` against
the resident kernel / DuckDB.
"""

KERNEL_SERVER_SOURCE = r"""
import json
import sys
import threading
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _run_and_callback(payload):
    envelope = {
        "status": "ok",
        "columns": ["count"],
        "row_count": 1,
        "first_page": [[42]],
        "result_id": str(uuid.uuid4()),
    }
    request = urllib.request.Request(
        payload["callback_url"],
        data=json.dumps({"envelope": envelope}).encode(),
        headers={
            "Authorization": "Bearer " + payload["callback_token"],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=15)
    except Exception as exc:  # noqa: BLE001 — best-effort callback; log and move on
        print("data_v2 kernel-server callback failed", exc, flush=True)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/run":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, ValueError):
            self.send_response(400)
            self.end_headers()
            return
        threading.Thread(target=_run_and_callback, args=(payload,), daemon=True).start()
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"accepted": true}')

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 47821
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
"""
