from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any

import pytest

from products.query_performance_ai.scripts.backends.base import BackendError, ExecutionBackend, ExecutionResult
from products.query_performance_ai.scripts.server import (
    ServerInfo,
    generate_token,
    make_server,
    serve_forever_in_thread,
)


class _StubBackend(ExecutionBackend):
    """Returns scripted results so the server tests don't need ClickHouse."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.result: ExecutionResult | Exception = ExecutionResult(
            rows=[[1, "ok"]],
            elapsed_ms=12.5,
            rows_read=1,
            bytes_read=42,
            query_id="qid-123",
        )

    @property
    def name(self) -> str:
        return "stub"

    @property
    def target(self) -> str:
        return "stub-target"

    def run(self, sql: str, *, timeout_s: int) -> ExecutionResult:
        self.calls.append((sql, timeout_s))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def prompt_addendum(self) -> str:
        return "STUB ADDENDUM"


@pytest.fixture()
def server_fixture() -> Any:
    backend = _StubBackend()
    token = generate_token()
    info = ServerInfo(target=backend.target, prompt_addendum=backend.prompt_addendum())
    server = make_server(host="127.0.0.1", port=0, backend=backend, token=token, info=info)
    serve_forever_in_thread(server)
    port = server.server_address[1]
    yield server, backend, token, port
    server.shutdown()


def _request(port: int, *, path: str, method: str, token: str | None, body: dict | None = None) -> tuple[int, dict]:
    headers: dict[str, str] = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def test_info_returns_target_and_addendum(server_fixture) -> None:
    _server, _backend, token, port = server_fixture
    status, body = _request(port, path="/v1/info", method="GET", token=token)
    assert status == 200
    assert body["target"] == "stub-target"
    assert body["prompt_addendum"] == "STUB ADDENDUM"
    assert body["primary_metric"] == "latency_ms"


def test_run_happy_path(server_fixture) -> None:
    _server, backend, token, port = server_fixture
    status, body = _request(port, path="/v1/run", method="POST", token=token, body={"sql": "SELECT 1"})
    assert status == 200
    assert body["result"] == [[1, "ok"]]
    assert body["rows_returned"] == 1
    assert body["query_id"] == "qid-123"
    assert backend.calls == [("SELECT 1", 300)]


def test_missing_token_returns_401(server_fixture) -> None:
    _server, _backend, _token, port = server_fixture
    status, body = _request(port, path="/v1/info", method="GET", token=None)
    assert status == 401
    assert body["error"] == "unauthorized"


def test_wrong_token_returns_401(server_fixture) -> None:
    _server, _backend, _token, port = server_fixture
    status, body = _request(port, path="/v1/info", method="GET", token="not-the-token")
    assert status == 401
    assert body["error"] == "unauthorized"


def test_run_rejects_empty_sql(server_fixture) -> None:
    _server, _backend, token, port = server_fixture
    status, body = _request(port, path="/v1/run", method="POST", token=token, body={"sql": ""})
    assert status == 400
    assert "non-empty" in body["error"]


def test_run_rejects_out_of_range_timeout(server_fixture) -> None:
    _server, _backend, token, port = server_fixture
    status, body = _request(
        port, path="/v1/run", method="POST", token=token, body={"sql": "SELECT 1", "timeout_s": 99999}
    )
    assert status == 400
    assert "timeout_s" in body["error"]


def test_run_returns_502_on_backend_error(server_fixture) -> None:
    _server, backend, token, port = server_fixture
    backend.result = BackendError("syntax exception")
    status, body = _request(port, path="/v1/run", method="POST", token=token, body={"sql": "SELECT bad"})
    assert status == 502
    assert "syntax" in body["error"]


def test_query_lock_serializes_concurrent_runs(server_fixture) -> None:
    """Multiple sandboxes posting /v1/run at the same time must NOT run
    backend.run() concurrently — the lock is the whole reason this server
    isn't just a thin wrapper."""
    _server, backend, token, port = server_fixture
    enter = threading.Event()
    release = threading.Event()
    in_flight = 0
    max_in_flight = 0
    counter_lock = threading.Lock()

    def slow_run(sql: str, *, timeout_s: int) -> ExecutionResult:
        nonlocal in_flight, max_in_flight
        with counter_lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        enter.set()
        release.wait(timeout=2)
        with counter_lock:
            in_flight -= 1
        return ExecutionResult(rows=[[1]], elapsed_ms=1.0, rows_read=None, bytes_read=None, query_id=None)

    backend.run = slow_run

    def hit() -> int:
        status, _body = _request(port, path="/v1/run", method="POST", token=token, body={"sql": "SELECT 1"})
        return status

    t1 = threading.Thread(target=hit)
    t2 = threading.Thread(target=hit)
    t1.start()
    enter.wait(timeout=2)  # first call is in flight
    t2.start()
    # Briefly let the second request reach the lock; assert in_flight stays at 1.
    import time as _time

    _time.sleep(0.1)
    assert max_in_flight == 1, "the coordinator's lock didn't serialize /v1/run"
    release.set()
    t1.join(timeout=5)
    t2.join(timeout=5)
