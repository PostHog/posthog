"""The kernel-server HTTP entry point.

Launched inside the sandbox as `python -m nb_kernel.server --port … --secret-file …
--version …`. Routes:

- GET /health → {"status": "ok", "version": …} — the version is the package
  content hash the backend deployed, used for the redeploy handshake.
- POST /run → verifies the HMAC command token, returns 202, executes the run and
  delivers the result callback on a background thread.
"""

import json
import logging
import argparse
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .auth import verify_command_token
from .runner import execute_run

DEFAULT_PORT = 47821

_config: dict[str, str] = {"secret": "", "version": "unknown"}


class KernelServerHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self._respond(200, {"status": "ok", "version": _config["version"]})
        else:
            self._respond(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if self.path != "/run":
            self._respond(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, ValueError):
            self._respond(400, {"error": "Invalid JSON body"})
            return
        if not verify_command_token(_config["secret"], payload.get("run_id", ""), self._bearer_token()):
            self._respond(401, {"error": "Invalid command token"})
            return
        threading.Thread(target=execute_run, args=(payload,), daemon=True).start()
        self._respond(202, {"accepted": True})

    def _bearer_token(self) -> str:
        authorization = self.headers.get("Authorization", "")
        return authorization[len("Bearer ") :].strip() if authorization.startswith("Bearer ") else ""

    def _respond(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: Any) -> None:
        pass


def main() -> None:
    logging.basicConfig(level=logging.INFO)  # stdout/stderr land in the server log file
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--secret-file", required=True)
    parser.add_argument("--version", default="unknown")
    args = parser.parse_args()

    with open(args.secret_file) as secret_file:
        _config["secret"] = secret_file.read().strip()
    _config["version"] = args.version

    ThreadingHTTPServer(("0.0.0.0", args.port), KernelServerHandler).serve_forever()


if __name__ == "__main__":
    main()
