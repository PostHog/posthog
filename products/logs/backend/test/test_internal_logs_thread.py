import os
import json
import time
import asyncio
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from aioresponses import CallbackResult, aioresponses
from prometheus_client import REGISTRY

from posthog.internal_logs import send_internal_log
from posthog.models.team import Team
from posthog.test.waiting import wait_until

from products.logs.backend import internal_logs_thread
from products.logs.backend.internal_logs_thread import TOKEN_CACHE_TTL_SECONDS, _read_api_token

URL = "http://capture-logs.test/i/v1/logs"
THREAD_NAME = "internal-logs-producer"
WAIT_SECONDS = 10


def _loop_threads() -> set[threading.Thread]:
    return {thread for thread in threading.enumerate() if thread.name == THREAD_NAME}


def _stop_loop_thread(threads: set[threading.Thread]) -> None:
    loop, producer = internal_logs_thread._loop, internal_logs_thread._producer
    if loop is not None and producer is not None:
        asyncio.run_coroutine_threadsafe(producer.drain(0), loop).result(WAIT_SECONDS)
        loop.call_soon_threadsafe(loop.stop)
    for thread in threads:
        thread.join(WAIT_SECONDS)


@pytest.fixture(autouse=True)
def started_threads(monkeypatch: pytest.MonkeyPatch, settings: Any) -> Iterator[Callable[[], set[threading.Thread]]]:
    before = _loop_threads()
    settings.LOGS_INTERNAL_PRODUCER_URL = URL
    settings.LOGS_INTERNAL_INGESTION_SIGNING_KEYS = "k1"
    settings.LOGS_INTERNAL_PRODUCER_TEAMS = "1"
    monkeypatch.setattr(internal_logs_thread, "_read_api_token", lambda team_id: "phc_test_token")
    monkeypatch.setattr(internal_logs_thread, "_drain", lambda *args: None)
    for name in ("_pid", "_producer", "_loop"):
        monkeypatch.setattr(internal_logs_thread, name, None)
    yield lambda: _loop_threads() - before
    _stop_loop_thread(_loop_threads() - before)


@pytest.fixture
def received() -> Iterator[tuple[list[dict[str, Any]], threading.Event]]:
    bodies: list[dict[str, Any]] = []
    arrived = threading.Event()

    def record(url: Any, **kwargs: Any) -> CallbackResult:
        bodies.append(json.loads(kwargs["data"]))
        arrived.set()
        return CallbackResult(status=200)

    with aioresponses() as capture_logs:
        capture_logs.post(URL, callback=record, repeat=True)
        yield bodies, arrived


def _send(team_id: int = 1, message: str = "hello") -> None:
    send_internal_log(
        "endpoints",
        team_id=team_id,
        log_source_id="endpoint-1",
        instance_id="run-1",
        timestamp=datetime(2025, 1, 15, 12, 37, 11, tzinfo=UTC),
        level="ERROR",
        message=message,
    )


def _records(bodies: list[dict[str, Any]]) -> list[tuple[str, int]]:
    return [
        (record["body"]["stringValue"], record["severityNumber"])
        for body in bodies
        for record in body["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
    ]


def test_send_from_a_sync_thread_reaches_capture_logs(received: tuple[list[dict[str, Any]], threading.Event]) -> None:
    bodies, arrived = received

    _send()

    assert arrived.wait(WAIT_SECONDS)
    assert _records(bodies) == [("hello", 17)]


@pytest.mark.parametrize(
    "setting, value, team_id",
    [
        pytest.param("LOGS_INTERNAL_PRODUCER_URL", "", 1, id="no url"),
        pytest.param("LOGS_INTERNAL_INGESTION_SIGNING_KEYS", "", 1, id="no signing keys"),
        pytest.param("LOGS_INTERNAL_PRODUCER_TEAMS", "1", 2, id="team not allowed"),
    ],
)
def test_send_starts_no_thread_when_nothing_is_sent(
    started_threads: Callable[[], set[threading.Thread]], settings: Any, setting: str, value: str, team_id: int
) -> None:
    setattr(settings, setting, value)

    _send(team_id=team_id)

    assert started_threads() == set()


def test_send_in_a_forked_child_starts_its_own_loop(
    monkeypatch: pytest.MonkeyPatch,
    started_threads: Callable[[], set[threading.Thread]],
    received: tuple[list[dict[str, Any]], threading.Event],
) -> None:
    bodies, arrived = received
    _send(message="parent")
    assert arrived.wait(WAIT_SECONDS)
    arrived.clear()
    _stop_loop_thread(started_threads())
    monkeypatch.setattr(os, "getpid", lambda: -1)

    _send(message="child")

    assert arrived.wait(WAIT_SECONDS)
    assert _records(bodies) == [("parent", 17), ("child", 17)]


def test_send_after_a_failed_thread_start_starts_the_loop(
    monkeypatch: pytest.MonkeyPatch, received: tuple[list[dict[str, Any]], threading.Event]
) -> None:
    bodies, arrived = received
    start = threading.Thread.start

    def fail_once(thread: threading.Thread) -> None:
        monkeypatch.setattr(threading.Thread, "start", start)
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", fail_once)
    with pytest.raises(RuntimeError):
        _send(message="first")
    assert internal_logs_thread._loop is None
    assert internal_logs_thread._pending_bytes == 0

    _send(message="second")

    assert arrived.wait(WAIT_SECONDS)
    assert _records(bodies) == [("second", 17)]


def _dropped_records() -> float:
    return (
        REGISTRY.get_sample_value("logs_internal_producer_records_total", {"source": "endpoints", "outcome": "dropped"})
        or 0
    )


def test_send_drops_entries_past_the_budget_while_the_loop_is_stalled(
    settings: Any, received: tuple[list[dict[str, Any]], threading.Event]
) -> None:
    settings.LOGS_INTERNAL_PRODUCER_MAX_BUFFERED_BYTES = 12_000
    _send()
    loop = internal_logs_thread._loop
    assert loop is not None
    stall = threading.Event()
    loop.call_soon_threadsafe(stall.wait, WAIT_SECONDS)
    dropped_before = _dropped_records()

    for _ in range(5):
        _send(message="x" * 4_000)

    assert internal_logs_thread._pending_bytes <= 12_000
    assert _dropped_records() - dropped_before == 3
    stall.set()
    wait_until(lambda: internal_logs_thread._pending_bytes == 0, timeout=WAIT_SECONDS)


@pytest.mark.django_db
def test_read_api_token_reads_postgres_once_per_team_within_the_ttl(
    monkeypatch: pytest.MonkeyPatch, team: Any, django_assert_num_queries: Any
) -> None:
    monkeypatch.setattr(internal_logs_thread, "_token_cache", {})

    with django_assert_num_queries(1):
        assert _read_api_token(team.id) == team.api_token
        assert _read_api_token(team.id) == team.api_token


@pytest.mark.django_db
def test_read_api_token_picks_up_a_rotated_token_after_the_ttl(monkeypatch: pytest.MonkeyPatch, team: Any) -> None:
    monkeypatch.setattr(internal_logs_thread, "_token_cache", {})
    start = time.monotonic()
    monkeypatch.setattr(internal_logs_thread.time, "monotonic", lambda: start)
    original_token = team.api_token
    assert _read_api_token(team.id) == original_token
    Team.objects.filter(id=team.id).update(api_token="phc_rotated_token")

    assert _read_api_token(team.id) == original_token
    monkeypatch.setattr(internal_logs_thread.time, "monotonic", lambda: start + TOKEN_CACHE_TTL_SECONDS + 1)
    assert _read_api_token(team.id) == "phc_rotated_token"


@pytest.mark.django_db
def test_read_api_token_does_not_cache_a_missing_team(
    monkeypatch: pytest.MonkeyPatch, team: Any, django_assert_num_queries: Any
) -> None:
    monkeypatch.setattr(internal_logs_thread, "_token_cache", {})

    with django_assert_num_queries(2):
        assert _read_api_token(team.id + 1) is None
        assert _read_api_token(team.id + 1) is None
