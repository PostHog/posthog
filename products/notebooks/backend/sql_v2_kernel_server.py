"""Source of the in-sandbox SQLV2 kernel-server.

This is NOT imported by Django — the string below is written into the notebook
sandbox and launched there (stdlib-only, no third-party deps). It mirrors PostHog
Code's agent-server: a long-running HTTP server the backend POSTs a run to with a
single request, instead of transferring a script per run.

`POST /run` accepts {run_id, code, callback_url, callback_token}, verifies the
HMAC command token in the Authorization header (analogue of agent-server's
connection JWT), returns 202, and does the work + result callback on a background
thread. For the Journey 1 slice it fabricates the result (42); a later version
runs `code` against the resident kernel / DuckDB.

The `_verify_command_token` check below must stay in sync with
`sql_v2.verify_command_token` (same HMAC scheme); the round-trip is unit-tested.
"""

KERNEL_SERVER_SOURCE = r"""
import hashlib
import hmac
import json
import sys
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SECRET = ""


def _verify_command_token(run_id, token):
    if not SECRET or not token:
        return False
    try:
        token_run_id, exp_str, signature = token.rsplit(".", 2)
        exp = int(exp_str)
    except (ValueError, AttributeError):
        return False
    if token_run_id != run_id or exp < int(time.time()):
        return False
    expected = hmac.new(SECRET.encode(), (token_run_id + "." + exp_str).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


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
        print("sql_v2 kernel-server callback failed", exc, flush=True)


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
        authorization = self.headers.get("Authorization", "")
        token = authorization[len("Bearer ") :].strip() if authorization.startswith("Bearer ") else ""
        if not _verify_command_token(payload.get("run_id", ""), token):
            self.send_response(401)
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
    if len(sys.argv) > 2:
        try:
            with open(sys.argv[2]) as secret_file:
                SECRET = secret_file.read().strip()
        except OSError:
            SECRET = ""
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
"""
