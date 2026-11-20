import re
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import time_machine

from aioresponses import CallbackResult, aioresponses
from prometheus_client import REGISTRY

from products.logs.backend.internal_logs import sign_internal_logs
from products.logs.backend.internal_logs_producer import (
    MAX_MESSAGE_LENGTH,
    GetTeamApiToken,
    InternalLogEntry,
    InternalLogsProducer,
    InternalLogsProducerConfig,
)

PARITY_FIXTURE = Path(__file__).parents[4] / "nodejs/src/logs/parity/fixtures/modules/internal_verify.json"
SIGNED = re.compile(r"^v1\.([a-z0-9_]+)\.([0-9]{10})\.[0-9a-f]{64}$")

URL = "http://capture-logs.test/i/v1/logs"
OUTCOMES = ["sent", "rejected", "failed", "dropped", "unknown_team", "abandoned", "invalid"]


def test_signer_reproduces_every_signature_in_the_node_parity_fixture() -> None:
    cases = json.loads(PARITY_FIXTURE.read_text())["cases"]
    signatures = [c["input"]["signature"] for c in cases if SIGNED.match(c["input"]["signature"] or "")]
    assert signatures
    for signature in signatures:
        match = SIGNED.match(signature)
        assert match is not None
        source, epoch_seconds = match.group(1), int(match.group(2))
        signed_at = datetime.fromtimestamp(epoch_seconds, tz=UTC)
        reproduced = {
            sign_internal_logs(keys, source, team_id, signed_at) for keys in ("k1,k0", "k0") for team_id in (1, 2)
        }
        assert signature in reproduced


def _outcome_counts() -> dict[str, float]:
    return {
        outcome: REGISTRY.get_sample_value(
            "logs_internal_producer_records_total", {"source": "hog_flow", "outcome": outcome}
        )
        or 0.0
        for outcome in OUTCOMES
    }


async def _api_token(team_id: int) -> str | None:
    return "phc_test_token"


async def _no_team(team_id: int) -> str | None:
    return None


def _producer(
    get_team_api_token: GetTeamApiToken = _api_token,
    max_in_flight: int = 2,
    max_buffered_bytes: int = 1024 * 1024,
    retry_timeout_ms: int = 10_000,
) -> InternalLogsProducer:
    return InternalLogsProducer(
        InternalLogsProducerConfig(
            url=URL,
            signing_keys="k1,k0",
            teams="1",
            max_in_flight=max_in_flight,
            max_buffered_bytes=max_buffered_bytes,
            retry_timeout_ms=retry_timeout_ms,
        ),
        get_team_api_token,
    )


def _entry(team_id: int = 1, level: str = "info", message: str = "hello") -> InternalLogEntry:
    return InternalLogEntry(
        team_id=team_id,
        log_source_id="flow-1",
        instance_id="run-1",
        timestamp=datetime(2025, 1, 15, 12, 37, 11, tzinfo=UTC),
        level=level,
        message=message,
    )


@pytest.mark.parametrize(
    "statuses, setup, expected",
    [
        pytest.param([503, 200], {}, {"sent": 1}, id="sent after a retry"),
        pytest.param([400], {}, {"rejected": 1}, id="rejected"),
        pytest.param([302], {}, {"rejected": 1}, id="redirect rejected"),
        pytest.param([503], {"retry_timeout_ms": 50, "jitter": 1.0}, {"failed": 1}, id="retries run out"),
        pytest.param([], {"get_team_api_token": _no_team}, {"unknown_team": 1}, id="unknown team"),
        pytest.param([], {"level": None}, {"invalid": 1}, id="invalid record"),
        pytest.param([], {"max_buffered_bytes": 1}, {"dropped": 1}, id="buffer full"),
        pytest.param([], {"drain_timeout_seconds": 0}, {"abandoned": 1}, id="drain times out"),
    ],
)
async def test_producer_counts_each_record_once_by_outcome(
    monkeypatch: pytest.MonkeyPatch,
    statuses: list[int],
    setup: dict[str, Any],
    expected: dict[str, int],
) -> None:
    monkeypatch.setattr(random, "random", lambda: setup.get("jitter", 0.0))
    producer = _producer(
        get_team_api_token=setup.get("get_team_api_token", _api_token),
        max_buffered_bytes=setup.get("max_buffered_bytes", 1024 * 1024),
        retry_timeout_ms=setup.get("retry_timeout_ms", 10_000),
    )
    entries = [_entry(team_id=team_id, level=setup.get("level", "info")) for team_id in (1, 2)]
    before = _outcome_counts()

    with aioresponses() as mocked:
        for status in statuses:
            mocked.post(URL, status=status, headers={"Location": "http://capture-logs.test/elsewhere"})
        producer.enqueue("hog_flow", entries)
        producer.flush()
        await producer.drain(timeout_seconds=setup.get("drain_timeout_seconds", 5))

    after = _outcome_counts()
    assert {outcome: after[outcome] - before[outcome] for outcome in OUTCOMES} == {
        outcome: expected.get(outcome, 0) for outcome in OUTCOMES
    }
    assert REGISTRY.get_sample_value("logs_internal_producer_buffered_bytes") == 0
    assert REGISTRY.get_sample_value("logs_internal_producer_in_flight_requests") == 0
    calls = [call for url_calls in mocked.requests.values() for call in url_calls]
    assert len(calls) == len(statuses)
    for call in calls:
        assert call.kwargs["headers"]["Authorization"] == "Bearer phc_test_token"
        assert call.kwargs["headers"]["x-posthog-internal"].startswith("v1.hog_flow.")


async def test_producer_splits_large_batches_and_caps_requests_in_flight() -> None:
    producer = _producer(max_in_flight=1, max_buffered_bytes=16 * 1024 * 1024)
    in_flight_at_each_call: list[float | None] = []
    before = _outcome_counts()

    def record_in_flight(url: object, **kwargs: object) -> CallbackResult:
        in_flight_at_each_call.append(REGISTRY.get_sample_value("logs_internal_producer_in_flight_requests"))
        return CallbackResult(status=200)

    with aioresponses() as mocked:
        mocked.post(URL, callback=record_in_flight, repeat=True)
        producer.enqueue("hog_flow", [_entry(message="x" * MAX_MESSAGE_LENGTH) for _ in range(9)])
        producer.flush()
        await producer.drain(timeout_seconds=5)

    calls = [call for url_calls in mocked.requests.values() for call in url_calls]
    assert [
        len(json.loads(call.kwargs["data"])["resourceLogs"][0]["scopeLogs"][0]["logRecords"]) for call in calls
    ] == [7, 2]
    assert all(len(call.kwargs["data"]) < 2 * 1024 * 1024 for call in calls)
    assert in_flight_at_each_call == [1, 1]
    assert _outcome_counts()["sent"] - before["sent"] == 9


async def test_producer_signs_each_retry_again() -> None:
    signed_at = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
    producer = _producer(max_in_flight=1)
    entry = _entry()

    with time_machine.travel(signed_at, tick=False) as clock, aioresponses() as mocked:

        def hang_past_the_signature_window(url: object, **kwargs: object) -> CallbackResult:
            clock.shift(10 * 60)
            return CallbackResult(status=503)

        mocked.post(URL, callback=hang_past_the_signature_window)
        mocked.post(URL, status=200)
        producer.enqueue("hog_flow", [entry])
        producer.flush()
        await producer.drain(timeout_seconds=5)

    calls = [call for url_calls in mocked.requests.values() for call in url_calls]
    assert [call.kwargs["headers"]["x-posthog-internal"] for call in calls] == [
        sign_internal_logs("k1", "hog_flow", 1, signed_at),
        sign_internal_logs("k1", "hog_flow", 1, signed_at + timedelta(minutes=10)),
    ]


@pytest.mark.parametrize(
    "retry_timeout_ms, expected_seconds",
    [
        pytest.param(300_000, 30, id="30 seconds, like a Kafka request"),
        pytest.param(2_000, 2, id="ends with the retry window"),
    ],
)
async def test_the_timeout_of_one_attempt(retry_timeout_ms: int, expected_seconds: float) -> None:
    producer = _producer(retry_timeout_ms=retry_timeout_ms)

    with aioresponses() as mocked:
        mocked.post(URL, status=200)
        producer.enqueue("hog_flow", [_entry()])
        producer.flush()
        await producer.drain(timeout_seconds=5)

    [call] = [call for url_calls in mocked.requests.values() for call in url_calls]
    assert call.kwargs["timeout"].total == pytest.approx(expected_seconds, abs=0.01)
