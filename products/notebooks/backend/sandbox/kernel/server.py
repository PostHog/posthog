"""The kernel-server HTTP entry point.

Launched inside the sandbox as `python -m nb_kernel.server --port … --secret-file …
--version …`. Routes:

- GET /health → {"status": "ok", "version": …} — the version is the package
  content hash the backend deployed, used for the redeploy handshake.
- POST /run → verifies the HMAC command token, returns 202, executes the run and
  delivers the result callback on a background thread.
- POST /page → verifies the HMAC command token, synchronously re-queries the data
  plane with the request's LIMIT/OFFSET and returns the rows in the 200 response.
  A page fetch is bounded, so it is plain request/response — no callback.
"""

import json
import logging
import argparse
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .auth import verify_command_token
from .runner import execute_run, fetch_page

DEFAULT_PORT = 47821

_config: dict[str, str] = {"secret": "", "version": "unknown"}


class KernelServerHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self._respond(200, {"status": "ok", "version": _config["version"]})
        else:
            self._respond(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if self.path not in ("/run", "/page", "/interrupt"):
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
        if self.path == "/run":
            threading.Thread(target=execute_run, args=(payload,), daemon=True).start()
            self._respond(202, {"accepted": True})
            return
        if self.path == "/interrupt":
            self._handle_interrupt()
            return
        self._handle_page(payload)

    def _handle_interrupt(self) -> None:
        # Deferred so the server startup path never imports jupyter_client (sandbox-only).
        from . import executor  # noqa: PLC0415 — keeps jupyter_client off the server import path

        executor.get_executor().interrupt()
        self._respond(200, {"interrupted": True})

    def _handle_page(self, payload: dict[str, Any]) -> None:
        from . import data_plane  # noqa: PLC0415 — keep pyarrow off the server startup path

        try:
            self._respond(200, fetch_page(payload))
        except data_plane.DataPlaneError as exc:
            self._respond(400, {"error": str(exc)})
        except Exception:  # noqa: BLE001 — a page failure must not kill the request thread silently
            logging.getLogger(__name__).exception("nb_kernel page fetch failed")
            self._respond(500, {"error": "Page fetch failed in the sandbox"})

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
