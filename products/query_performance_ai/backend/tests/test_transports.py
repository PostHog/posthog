"""Tests for the in-sandbox `CoordinatorTransport`.

The transport runs inside the sandbox and posts to the coordinator's HTTP
server. We stub the HTTP server with a stdlib BaseHTTPRequestHandler and
exercise the transport against it — black-box, no urllib mocks.
"""

from __future__ import annotations

import sys
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

# transports.py is meant to be imported as a sibling script inside the sandbox;
# load it directly so the test process doesn't have to pretend to be the sandbox.
_AUTORESEARCH_SCRIPTS = Path(__file__).resolve().parents[2] / "autoresearch" / "scripts"
sys.path.insert(0, str(_AUTORESEARCH_SCRIPTS))
import transports  # type: ignore[import-not-found]  # noqa: E402


@pytest.fixture()
def fake_coordinator() -> Any:
    state: dict[str, Any] = {
        "expect_token": "tok",
        "response_status": 200,
        "response_body": json.dumps(
            {
                "result": [[1, "x"]],
                "rows_returned": 1,
                "elapsed_ms": 12.5,
                "rows_read": 7,
                "bytes_read": 99,
                "query_id": "qid",
            }
        ),
        "received_body": None,
        "received_auth": None,
    }

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any, **_kwargs: Any) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            state["received_body"] = body.decode("utf-8")
            state["received_auth"] = self.headers.get("Authorization")
            payload = state["response_body"].encode("utf-8")
            self.send_response(state["response_status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    yield state, port
    server.shutdown()


def test_coordinator_transport_happy_path(fake_coordinator) -> None:
    state, port = fake_coordinator
    transport = transports.CoordinatorTransport(base_url=f"http://127.0.0.1:{port}", token="tok")
    result = transport.run("SELECT 1")
    assert result.elapsed_ms == 12.5
    assert result.rows_read == 7
    assert result.bytes_read == 99
    assert result.query_id == "qid"
    assert result.result_bytes == b'[1,"x"]\n'

    received = json.loads(state["received_body"])
    assert received["sql"] == "SELECT 1"
    assert state["received_auth"] == "Bearer tok"


def test_coordinator_transport_4xx_raises(fake_coordinator) -> None:
    state, port = fake_coordinator
    state["response_status"] = 401
    state["response_body"] = json.dumps({"error": "unauthorized"})
    transport = transports.CoordinatorTransport(base_url=f"http://127.0.0.1:{port}", token="wrong")
    with pytest.raises(transports.TransportError, match="401"):
        transport.run("SELECT 1")


def test_coordinator_transport_502_raises(fake_coordinator) -> None:
    state, port = fake_coordinator
    state["response_status"] = 502
    state["response_body"] = json.dumps({"error": "ch error"})
    transport = transports.CoordinatorTransport(base_url=f"http://127.0.0.1:{port}", token="tok")
    with pytest.raises(transports.TransportError, match="502"):
        transport.run("SELECT 1")


def test_coordinator_transport_non_json_raises(fake_coordinator) -> None:
    state, port = fake_coordinator
    state["response_body"] = "this is not json"
    transport = transports.CoordinatorTransport(base_url=f"http://127.0.0.1:{port}", token="tok")
    with pytest.raises(transports.TransportError, match="non-JSON"):
        transport.run("SELECT 1")


def test_coordinator_transport_rejects_non_http_scheme() -> None:
    transport = transports.CoordinatorTransport(base_url="file:///etc/passwd", token="tok")
    with pytest.raises(ValueError, match="scheme"):
        transport.run("SELECT 1")


def test_load_transport_requires_coordinator_type() -> None:
    with pytest.raises(ValueError, match='must be "coordinator"'):
        transports.load_transport({"type": "posthog_proxy", "url": "http://x", "token": "t"})


def test_load_transport_requires_url_and_token() -> None:
    with pytest.raises(ValueError, match='"url"'):
        transports.load_transport({"type": "coordinator", "token": "t"})
    with pytest.raises(ValueError, match='"token"'):
        transports.load_transport({"type": "coordinator", "url": "http://x"})
