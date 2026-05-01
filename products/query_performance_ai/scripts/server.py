"""Coordinator HTTP server.

stdlib `http.server` so we can run with no extra deps in a fresh worktree.
The single chokepoint that the sandbox hits — token-gated, scheme-locked
to localhost, and serializing all SQL execution behind one lock so a fan
of parallel sandboxes doesn't translate into a fan of parallel ClickHouse
queries.
"""

from __future__ import annotations

import hmac
import json
import secrets
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import BaseServer
from typing import Any

from .backends.base import BackendError, ExecutionBackend


@dataclass(frozen=True)
class ServerInfo:
    """Payload for `GET /v1/info`. Mirrors what run_campaign.py needs."""

    target: str
    prompt_addendum: str
    primary_metric: str = "latency_ms"
    capture_baseline_in_orchestrator: bool = True


class CoordinatorServer(ThreadingHTTPServer):
    """Exposes `_backend`, `_token`, `_info`, `_query_lock` to the handler.

    `ThreadingHTTPServer` lets `/v1/info` from one sandbox not block on
    the slow `/v1/run` of another — but the lock around `_backend.run()`
    still guarantees only one query is in flight at a time.
    """

    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        RequestHandlerClass: type[BaseHTTPRequestHandler],
        *,
        backend: ExecutionBackend,
        token: str,
        info: ServerInfo,
    ):
        super().__init__(server_address, RequestHandlerClass)
        self._backend = backend
        self._token = token
        self._info = info
        self._query_lock = threading.Lock()


class CoordinatorHandler(BaseHTTPRequestHandler):
    server: CoordinatorServer  # narrows the type for handler code

    # http.server logs every request to stderr by default; the coordinator
    # already has its own logging so suppress the duplicate noise.
    def log_message(self, format: str, *args: Any) -> None:
        return

    # ----- helpers -----
    def _read_json_body(self) -> dict[str, Any]:
        length_header = self.headers.get("Content-Length") or "0"
        try:
            length = int(length_header)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        # Cap at 1 MiB — campaign SQL is usually a few KiB; nothing legitimate
        # is bigger than this and clamping prevents a malformed Content-Length
        # from making us read forever.
        if length > 1 << 20:
            raise _BadRequest("body too large")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise _BadRequest(f"invalid JSON body: {e}") from e
        if not isinstance(data, dict):
            raise _BadRequest("body must be a JSON object")
        return data

    def _check_auth(self) -> None:
        header = self.headers.get("Authorization") or ""
        prefix = "Bearer "
        if not header.startswith(prefix):
            raise _Unauthorized()
        provided = header[len(prefix) :]
        if not hmac.compare_digest(provided, self.server._token):
            raise _Unauthorized()

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ----- routes -----
    def do_GET(self) -> None:  # noqa: N802 — http.server convention
        try:
            self._check_auth()
            if self.path == "/v1/info":
                info = self.server._info
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "target": info.target,
                        "prompt_addendum": info.prompt_addendum,
                        "primary_metric": info.primary_metric,
                        "capture_baseline_in_orchestrator": info.capture_baseline_in_orchestrator,
                    },
                )
                return
            if self.path == "/v1/healthz":
                self._send_json(HTTPStatus.OK, {"ok": True})
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except _Unauthorized:
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})

    def do_POST(self) -> None:  # noqa: N802 — http.server convention
        try:
            self._check_auth()
            if self.path != "/v1/run":
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return

            body = self._read_json_body()
            sql = body.get("sql")
            if not isinstance(sql, str) or not sql.strip():
                raise _BadRequest("`sql` must be a non-empty string")
            timeout_s_raw = body.get("timeout_s", 300)
            try:
                timeout_s = int(timeout_s_raw)
            except (TypeError, ValueError) as e:
                raise _BadRequest("`timeout_s` must be an integer") from e
            if not 1 <= timeout_s <= 600:
                raise _BadRequest("`timeout_s` must be between 1 and 600")

            with self.server._query_lock:
                try:
                    result = self.server._backend.run(sql, timeout_s=timeout_s)
                except BackendError as e:
                    self._send_json(HTTPStatus.BAD_GATEWAY, {"error": str(e)})
                    return

            self._send_json(
                HTTPStatus.OK,
                {
                    "result": result.rows,
                    "rows_returned": len(result.rows),
                    "elapsed_ms": result.elapsed_ms,
                    "rows_read": result.rows_read,
                    "bytes_read": result.bytes_read,
                    "query_id": result.query_id,
                },
            )
        except _Unauthorized:
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
        except _BadRequest as e:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})


class _Unauthorized(Exception):
    pass


class _BadRequest(Exception):
    pass


def make_server(
    *,
    host: str,
    port: int,
    backend: ExecutionBackend,
    token: str,
    info: ServerInfo,
) -> CoordinatorServer:
    return CoordinatorServer((host, port), CoordinatorHandler, backend=backend, token=token, info=info)


def generate_token() -> str:
    """32 bytes of entropy → 43 char URL-safe string."""
    return secrets.token_urlsafe(32)


def serve_forever_in_thread(server: BaseServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, name="coordinator-http", daemon=True)
    thread.start()
    return thread
