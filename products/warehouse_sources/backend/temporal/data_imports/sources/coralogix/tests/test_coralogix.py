import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coralogix import coralogix as coralogix_module
from products.warehouse_sources.backend.temporal.data_imports.sources.coralogix.coralogix import (
    CoralogixResumeConfig,
    CoralogixRetryableError,
    _format_datetime,
    _make_session,
    _parse_timestamp,
    _run_query,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coralogix.source import CoralogixSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coralogix import (
    CoralogixSourceConfig,
)

NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
QUERY_URL = "https://api.eu2.coralogix.com/api/v1/dataprime/query"


def _result_item(ts: str, logid: str) -> dict:
    return {
        "metadata": [{"key": "logid", "value": logid}, {"key": "timestamp", "value": ts}],
        "labels": [{"key": "applicationname", "value": "app"}],
        "userData": '{"msg": "x"}',
    }


def _ndjson_body(results: list[dict], extra_lines: list[dict] | None = None) -> bytes:
    lines = [json.dumps({"queryId": {"queryId": "q-1"}})]
    if results:
        lines.append(json.dumps({"result": {"results": results}}))
    for extra in extra_lines or []:
        lines.append(json.dumps(extra))
    lines.append(json.dumps({"statistics": {"status": "COMPLETED"}}))
    return "\n".join(lines).encode()


def _ndjson_response(results: list[dict], status: int = 200, extra_lines: list[dict] | None = None) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = _ndjson_body(results, extra_lines)
    # Make iter_lines() serve the canned body instead of reading a (nonexistent) raw socket.
    resp._content_consumed = True  # type: ignore[attr-defined]
    resp.url = QUERY_URL
    return resp


class _FakeServer:
    # Simulates the query endpoint: returns fixture rows whose timestamp falls inside the
    # requested window, treating BOTH boundaries as inclusive — the client-side half-open filter
    # is what must prevent adjacent windows from double-counting boundary rows.
    def __init__(self, rows: list[tuple[datetime, str]]):
        self.rows = rows

    def __call__(self, request: RecordedRequest) -> ScriptedResponse:
        body = request.json()
        meta = body["metadata"]
        start = datetime.strptime(meta["startDate"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
        end = datetime.strptime(meta["endDate"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
        matching = [(ts, logid) for ts, logid in self.rows if start <= ts <= end]
        items = [_result_item(_format_datetime(ts), logid) for ts, logid in matching[: meta["limit"]]]
        return ScriptedResponse(body=_ndjson_body(items))


def _run_walker(
    server: _FakeServer,
    resume_state: CoralogixResumeConfig | None = None,
    endpoint: str = "logs",
    tier: str = "frequent_search",
    should_use_incremental_field: bool = False,
    last_value: Any = None,
    logger: MagicMock | None = None,
) -> DriveResult:
    config = CoralogixSourceConfig.from_dict({"api_key": "k", "domain": "eu2.coralogix.com", "tier": tier})
    driver = SourceDriver(CoralogixSource(), config)
    return driver.run(
        endpoint,
        server,
        resume_state=resume_state,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=last_value,
        logger=logger,
    )


class TestParseTimestamp:
    @parameterized.expand(
        [
            ("iso_z", "2026-01-15T10:00:00.500Z", datetime(2026, 1, 15, 10, 0, 0, 500000, tzinfo=UTC)),
            # Nanosecond fractions overflow datetime.fromisoformat; they must trim, not fail —
            # otherwise every row loses its timestamp and the watermark never advances.
            ("iso_nanoseconds", "2026-01-15T10:00:00.123456789Z", datetime(2026, 1, 15, 10, 0, 0, 123456, tzinfo=UTC)),
            ("iso_offset", "2026-01-15T02:00:00.00-08:00", datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)),
            ("iso_naive", "2026-01-15T10:00:00", datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)),
            ("epoch_seconds", 1768471200, datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)),
            ("epoch_millis", 1768471200000, datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)),
            ("epoch_micros", 1768471200000000, datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)),
            ("epoch_nanos", 1768471200000000000, datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)),
            ("epoch_string", "1768471200000", datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)),
            ("datetime_naive", datetime(2026, 1, 15, 10, 0, 0), datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)),
            ("garbage", "not-a-timestamp", None),
            ("empty", "", None),
            ("none", None, None),
        ]
    )
    def test_parses_to_utc(self, _name: str, value: Any, expected: datetime | None) -> None:
        assert _parse_timestamp(value) == expected


class TestMakeSession:
    def test_disables_sample_capture_and_redirects(self) -> None:
        # Log/span bodies are free-form user telemetry that can carry secrets the name-based
        # scrubbers can't recognise, so response capture must stay off; redirects stay pinned off
        # so a credentialed request can't be replayed against another host.
        with scripted_network([]) as network:
            _make_session("secret-key")
        assert network.session_options[0]["capture"] is False
        assert network.session_options[0]["allow_redirects"] is False
        assert network.session_options[0]["redact_values"] == ("secret-key",)


class TestRunQuery:
    def _query(self, response: Response) -> list[dict]:
        session = MagicMock()
        session.post.return_value = response
        return _run_query.__wrapped__(  # type: ignore[attr-defined]
            session, QUERY_URL, "logs", "TIER_FREQUENT_SEARCH", NOW - timedelta(hours=1), NOW, MagicMock()
        )

    def test_parses_result_lines_and_ignores_bookkeeping_lines(self) -> None:
        response = _ndjson_response(
            [_result_item("2026-01-15T10:00:00.000Z", "log-1")],
            extra_lines=[
                {"warning": {"timeRangeWarning": {}}},
                {"result": {"results": [_result_item("2026-01-15T10:01:00.000Z", "log-2")]}},
            ],
        )
        rows = self._query(response)
        assert [row["logid"] for row in rows] == ["log-1", "log-2"]

    def test_error_line_raises(self) -> None:
        with pytest.raises(Exception, match="Coralogix query error"):
            self._query(_ndjson_response([], extra_lines=[{"error": {"message": "boom"}}]))

    @parameterized.expand([(429,), (500,), (503,)])
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        with pytest.raises(CoralogixRetryableError):
            self._query(_ndjson_response([], status=status))

    def test_forbidden_raises_http_error(self) -> None:
        # 403 must surface as an HTTPError whose message the non-retryable matcher recognises.
        with pytest.raises(requests.HTTPError, match="403 Client Error"):
            self._query(_ndjson_response([], status=403))


class TestGetRows:
    def test_rejects_domains_outside_the_allowlist(self) -> None:
        # The generated config's Literal type is not validated when job inputs are parsed, so
        # the transport allowlist is what stops a crafted domain from redirecting the
        # credentialed request (SSRF / API-key exfiltration). It must fail before any HTTP.
        config = CoralogixSourceConfig.from_dict(
            {"api_key": "k", "domain": "coralogix.us@attacker.example", "tier": "frequent_search"}
        )
        result = SourceDriver(CoralogixSource(), config).run("logs", [])

        assert isinstance(result.raised, ValueError)
        assert "Unknown Coralogix domain" in str(result.raised)
        assert result.requests == []

    @time_machine.travel(NOW, tick=False)
    def test_walks_windows_without_double_counting_boundaries(self) -> None:
        watermark = NOW - timedelta(hours=2)
        boundary = NOW - timedelta(hours=1)
        server = _FakeServer(
            [
                # At the incremental watermark: yielded by the run that set it, must be dropped.
                (watermark, "at-watermark"),
                (NOW - timedelta(minutes=115), "in-first-window"),
                # Exactly on the window boundary: the inclusive fake server returns it for both
                # windows; the half-open client filter must keep it exactly once.
                (boundary, "on-boundary"),
                # Out of fixture-order relative to `on-boundary` to prove within-window sorting.
                (NOW - timedelta(minutes=30), "in-second-window"),
            ]
        )

        result = _run_walker(server, should_use_incremental_field=True, last_value=watermark)

        assert result.raised is None
        assert [row["logid"] for row in result.rows] == ["in-first-window", "on-boundary", "in-second-window"]
        # First window is [watermark, watermark+1h); the second grows (sparse) and clamps to now.
        first, second = (request.json() for request in result.requests)
        assert (first["metadata"]["startDate"], first["metadata"]["endDate"]) == (
            _format_datetime(watermark),
            _format_datetime(boundary),
        )
        assert (second["metadata"]["startDate"], second["metadata"]["endDate"]) == (
            _format_datetime(boundary),
            _format_datetime(NOW),
        )
        assert first["query"] == "source logs"
        assert first["metadata"]["tier"] == "TIER_FREQUENT_SEARCH"
        # State is saved at each completed window boundary and cleared once fully walked, so a
        # retry starts fresh from the new watermark instead of resuming mid-stream.
        assert result.saved_states == [
            CoralogixResumeConfig(synced_until=_format_datetime(boundary)),
            CoralogixResumeConfig(synced_until=_format_datetime(NOW)),
        ]
        assert result.final_state is None

    @time_machine.travel(NOW, tick=False)
    def test_bisects_windows_that_hit_the_row_cap(self) -> None:
        start = NOW - timedelta(hours=2)
        server = _FakeServer(
            [
                (start + timedelta(minutes=10), "r1"),
                (start + timedelta(minutes=40), "r2"),
                (start + timedelta(minutes=50), "r3"),
            ]
        )

        with patch.object(coralogix_module, "QUERY_LIMIT", 2):
            result = _run_walker(server, should_use_incremental_field=True, last_value=start)

        # Capped windows are re-queried with a smaller span rather than silently dropping the
        # rows beyond the cap: every fixture row arrives exactly once, in timestamp order.
        assert result.raised is None
        assert [row["logid"] for row in result.rows] == ["r1", "r2", "r3"]
        first, second = (request.json()["metadata"] for request in result.requests[:2])
        assert first["startDate"] == second["startDate"]  # first bisection retried the cursor
        assert second["endDate"] < first["endDate"]

    @time_machine.travel(NOW, tick=False)
    def test_min_window_cap_warns_and_advances(self) -> None:
        # A window at the minimum size that still hits the cap must warn (no silent truncation)
        # and advance — not bisect forever.
        start = NOW - timedelta(seconds=10)
        server = _FakeServer([(NOW - timedelta(seconds=8), "r1"), (NOW - timedelta(seconds=6), "r2")])
        logger = MagicMock()

        with patch.object(coralogix_module, "QUERY_LIMIT", 1):
            result = _run_walker(server, should_use_incremental_field=True, last_value=start, logger=logger)

        assert result.raised is None
        assert [row["logid"] for row in result.rows] == ["r1"]
        assert logger.warning.call_count == 1
        assert "cap" in logger.warning.call_args.args[0]

    @time_machine.travel(NOW, tick=False)
    def test_resumes_inclusively_from_saved_state(self) -> None:
        watermark = NOW - timedelta(hours=2)
        synced_until = NOW - timedelta(hours=1)
        server = _FakeServer(
            [
                (NOW - timedelta(minutes=90), "before-resume-point"),
                # Exactly at the resume boundary: it belonged to the *next* (unfinished) window,
                # so the inclusive restart must pick it up.
                (synced_until, "at-resume-point"),
            ]
        )

        result = _run_walker(
            server,
            resume_state=CoralogixResumeConfig(synced_until=_format_datetime(synced_until)),
            should_use_incremental_field=True,
            last_value=watermark,
        )

        assert result.raised is None
        assert result.requests[0].json()["metadata"]["startDate"] == _format_datetime(synced_until)
        assert [row["logid"] for row in result.rows] == ["at-resume-point"]


class TestCoralogixSource:
    @parameterized.expand([("logs", ["logid"]), ("spans", None)])
    def test_source_response_shape(self, endpoint: str, expected_primary_keys: list[str] | None) -> None:
        result = _run_walker(_FakeServer([]), endpoint=endpoint, tier="archive")
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        # Rows are sorted per window and windows advance chronologically, so per-batch watermark
        # checkpointing (asc) is safe; the partition key is the immutable event timestamp.
        assert response.sort_mode == "asc"
        assert response.partition_keys == ["timestamp"]


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True)])
    def test_maps_status_to_validity(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status, body=_ndjson_body([]))]) as network:
            assert validate_credentials("k", "coralogix.us") is expected
        assert network.requests_log[0].url == "https://api.coralogix.us/api/v1/dataprime/query"
