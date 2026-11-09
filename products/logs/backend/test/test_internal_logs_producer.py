import re
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import time_machine

from aioresponses import CallbackResult, aioresponses
from prometheus_client import REGISTRY

from products.logs.backend.internal_logs import sign_internal_logs
from products.logs.backend.internal_logs_producer import (
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


@pytest.mark.parametrize(
    "statuses, max_buffered_bytes, drain_timeout_seconds, expected",
    [
        ([503, 200], 1024 * 1024, 5, {"sent": 1}),
        ([400], 1024 * 1024, 5, {"rejected": 1}),
        ([302], 1024 * 1024, 5, {"rejected": 1}),
        ([], 1, 5, {"dropped": 1}),
        ([], 1024 * 1024, 0, {"abandoned": 1}),
    ],
)
async def test_producer_counts_each_record_once_by_outcome(
    monkeypatch: pytest.MonkeyPatch,
    statuses: list[int],
    max_buffered_bytes: int,
    drain_timeout_seconds: float,
    expected: dict[str, int],
) -> None:
    monkeypatch.setattr(random, "random", lambda: 0.0)
    producer = InternalLogsProducer(
        InternalLogsProducerConfig(
            url=URL,
            signing_keys="k1,k0",
            teams="1",
            max_in_flight=2,
            max_buffered_bytes=max_buffered_bytes,
            retry_timeout_ms=10_000,
        ),
        _api_token,
    )
    entries = [
        InternalLogEntry(
            team_id=team_id,
            log_source_id="flow-1",
            instance_id="run-1",
            timestamp=datetime(2025, 1, 15, 12, 37, 11, tzinfo=UTC),
            level="info",
            message="hello",
        )
        for team_id in (1, 2)
    ]
    before = _outcome_counts()

    with aioresponses() as mocked:
        for status in statuses:
            mocked.post(URL, status=status, headers={"Location": "http://capture-logs.test/elsewhere"})
        producer.enqueue("hog_flow", entries)
        producer.flush()
        await producer.drain(timeout_seconds=drain_timeout_seconds)

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


async def test_producer_signs_each_retry_again() -> None:
    signed_at = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
    producer = InternalLogsProducer(
        InternalLogsProducerConfig(
            url=URL,
            signing_keys="k1",
            teams="1",
            max_in_flight=1,
            max_buffered_bytes=1024 * 1024,
            retry_timeout_ms=10_000,
        ),
        _api_token,
    )
    entry = InternalLogEntry(
        team_id=1, log_source_id="flow-1", instance_id="run-1", timestamp=signed_at, level="info", message="hello"
    )

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
