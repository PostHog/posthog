import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.coralogix import coralogix as coralogix_module
from products.warehouse_sources.backend.temporal.data_imports.sources.coralogix.coralogix import (
    CoralogixResumeConfig,
    CoralogixRetryableError,
    _format_datetime,
    _make_session,
    _normalize_row,
    _parse_timestamp,
    _run_query,
    coralogix_source,
    get_rows,
    validate_credentials,
)

NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
QUERY_URL = "https://api.eu2.coralogix.com/api/v1/dataprime/query"


def _result_item(ts: str, logid: str) -> dict:
    return {
        "metadata": [{"key": "logid", "value": logid}, {"key": "timestamp", "value": ts}],
        "labels": [{"key": "applicationname", "value": "app"}],
        "userData": '{"msg": "x"}',
    }


def _ndjson_response(results: list[dict], status: int = 200, extra_lines: list[dict] | None = None) -> Response:
    lines = [json.dumps({"queryId": {"queryId": "q-1"}})]
    if results:
        lines.append(json.dumps({"result": {"results": results}}))
    for extra in extra_lines or []:
        lines.append(json.dumps(extra))
    lines.append(json.dumps({"statistics": {"status": "COMPLETED"}}))
    resp = Response()
    resp.status_code = status
    resp._content = "\n".join(lines).encode()
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
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, json: dict | None = None, stream: bool = False, timeout: Any = None) -> Response:
        assert json is not None
        meta = json["metadata"]
        start = datetime.strptime(meta["startDate"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
        end = datetime.strptime(meta["endDate"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
        self.calls.append(
            {"start": start, "end": end, "limit": meta["limit"], "query": json["query"], "tier": meta["tier"]}
        )
        matching = [(ts, logid) for ts, logid in self.rows if start <= ts <= end]
        items = [_result_item(_format_datetime(ts), logid) for ts, logid in matching[: meta["limit"]]]
        return _ndjson_response(items)


def _run_walker(
    server: _FakeServer,
    manager: MagicMock | None = None,
    endpoint: str = "logs",
    tier: str = "frequent_search",
    should_use_incremental_field: bool = False,
    last_value: Any = None,
) -> tuple[list[str], MagicMock, MagicMock]:
    manager = manager or _manager()
    logger = MagicMock()
    session = MagicMock()
    session.post.side_effect = server.post
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.coralogix.coralogix.make_tracked_session",
        return_value=session,
    ):
        batches = list(
            get_rows(
                api_key="k",
                domain="eu2.coralogix.com",
                tier=tier,
                endpoint=endpoint,
                logger=logger,
                resumable_source_manager=manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=last_value,
            )
        )
    logids = [row["logid"] for batch in batches for row in batch]
    return logids, manager, logger


def _manager(resume: CoralogixResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


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


class TestNormalizeRow:
    def test_flattens_metadata_and_labels_and_keeps_user_data_raw(self) -> None:
        row = _normalize_row(
            {
                "metadata": [
                    {"key": "timestamp", "value": "2026-01-15T10:00:00.000Z"},
                    {"key": "logid", "value": "log-1"},
                    {"key": "severity", "value": "Info"},
                ],
                "labels": [
                    {"key": "applicationname", "value": "app"},
                    # Collides with metadata; metadata must win.
                    {"key": "severity", "value": "label-severity"},
                ],
                "userData": '{"nested": {"deep": 1}}',
            }
        )
        assert row == {
            "timestamp": datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
            "logid": "log-1",
            "severity": "Info",
            "applicationname": "app",
            # The body stays a JSON string — flattening arbitrary telemetry would produce an
            # unstable column set.
            "user_data": '{"nested": {"deep": 1}}',
        }


class TestMakeSession:
    def test_disables_sample_capture_and_redirects(self) -> None:
        # Log/span bodies are free-form user telemetry that can carry secrets the name-based
        # scrubbers can't recognise, so response capture must stay off; redirects stay pinned off
        # so a credentialed request can't be replayed against another host.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.coralogix.coralogix.make_tracked_session"
        ) as make_session:
            _make_session("secret-key")
        assert make_session.call_args.kwargs["capture"] is False
        assert make_session.call_args.kwargs["allow_redirects"] is False
        assert make_session.call_args.kwargs["redact_values"] == ("secret-key",)


class TestRunQuery:
    def _query(self, response: Response) -> list[dict]:
        session = MagicMock()
        session.post.return_value = response
        return _run_query.__wrapped__(
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

    def test_stops_reading_a_misbehaving_stream_at_the_row_cap(self) -> None:
        # The request asks the server for at most QUERY_LIMIT rows; a response that keeps
        # streaming past it must not be accumulated unboundedly into memory.
        response = _ndjson_response(
            [_result_item("2026-01-15T10:00:00.000Z", "log-1")],
            extra_lines=[
                {"result": {"results": [_result_item("2026-01-15T10:01:00.000Z", "log-2")]}},
                {"result": {"results": [_result_item("2026-01-15T10:02:00.000Z", "log-3")]}},
            ],
        )
        with patch.object(coralogix_module, "QUERY_LIMIT", 2):
            rows = self._query(response)
        assert [row["logid"] for row in rows] == ["log-1", "log-2"]


class TestGetRows:
    def test_rejects_domains_outside_the_allowlist(self) -> None:
        # The generated config's Literal type is not validated when job inputs are parsed, so
        # the transport allowlist is what stops a crafted domain from redirecting the
        # credentialed request (SSRF / API-key exfiltration). It must fail before any HTTP.
        session = MagicMock()
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.coralogix.coralogix.make_tracked_session",
                return_value=session,
            ),
            pytest.raises(ValueError, match="Unknown Coralogix domain"),
        ):
            list(
                get_rows(
                    api_key="k",
                    domain="coralogix.us@attacker.example",
                    tier="frequent_search",
                    endpoint="logs",
                    logger=MagicMock(),
                    resumable_source_manager=_manager(),
                )
            )
        session.post.assert_not_called()

    @freeze_time(NOW)
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

        logids, manager, _logger = _run_walker(server, should_use_incremental_field=True, last_value=watermark)

        assert logids == ["in-first-window", "on-boundary", "in-second-window"]
        # First window is [watermark, watermark+1h); the second grows (sparse) and clamps to now.
        assert (server.calls[0]["start"], server.calls[0]["end"]) == (watermark, boundary)
        assert (server.calls[1]["start"], server.calls[1]["end"]) == (boundary, NOW)
        assert server.calls[0]["query"] == "source logs"
        assert server.calls[0]["tier"] == "TIER_FREQUENT_SEARCH"
        # State is saved at each completed window boundary and cleared once fully walked, so a
        # retry starts fresh from the new watermark instead of resuming mid-stream.
        saved = [call.args[0].synced_until for call in manager.save_state.call_args_list]
        assert saved == [_format_datetime(boundary), _format_datetime(NOW)]
        manager.clear_state.assert_called_once()

    @freeze_time(NOW)
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
            logids, _unused_manager, _unused_logger = _run_walker(
                server, should_use_incremental_field=True, last_value=start
            )

        # Capped windows are re-queried with a smaller span rather than silently dropping the
        # rows beyond the cap: every fixture row arrives exactly once, in timestamp order.
        assert logids == ["r1", "r2", "r3"]
        assert server.calls[0]["start"] == server.calls[1]["start"]  # first bisection retried the cursor
        assert server.calls[1]["end"] - server.calls[1]["start"] < server.calls[0]["end"] - server.calls[0]["start"]

    @freeze_time(NOW)
    def test_min_window_cap_warns_and_advances(self) -> None:
        # A window at the minimum size that still hits the cap must warn (no silent truncation)
        # and advance — not bisect forever.
        start = NOW - timedelta(seconds=10)
        server = _FakeServer([(NOW - timedelta(seconds=8), "r1"), (NOW - timedelta(seconds=6), "r2")])

        with patch.object(coralogix_module, "QUERY_LIMIT", 1):
            logids, _unused_manager, logger = _run_walker(server, should_use_incremental_field=True, last_value=start)

        assert logids == ["r1"]
        assert logger.warning.call_count == 1
        assert "cap" in logger.warning.call_args.args[0]

    @freeze_time(NOW)
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

        logids, _unused_manager, _unused_logger = _run_walker(
            server,
            manager=_manager(CoralogixResumeConfig(synced_until=_format_datetime(synced_until))),
            should_use_incremental_field=True,
            last_value=watermark,
        )

        assert server.calls[0]["start"] == synced_until
        assert logids == ["at-resume-point"]

    @freeze_time(NOW)
    def test_initial_sync_covers_the_default_lookback_contiguously(self) -> None:
        server = _FakeServer([])

        logids, _unused_manager, _unused_logger = _run_walker(server)

        assert logids == []
        assert server.calls[0]["start"] == NOW - timedelta(days=coralogix_module.DEFAULT_LOOKBACK_DAYS)
        assert server.calls[-1]["end"] == NOW
        for previous, current in zip(server.calls, server.calls[1:]):
            assert current["start"] == previous["end"]


class TestCoralogixSource:
    @parameterized.expand([("logs", ["logid"]), ("spans", None)])
    def test_source_response_shape(self, endpoint: str, expected_primary_keys: list[str] | None) -> None:
        response = coralogix_source(
            api_key="k",
            domain="eu2.coralogix.com",
            tier="archive",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        # Rows are sorted per window and windows advance chronologically, so per-batch watermark
        # checkpointing (asc) is safe; the partition key is the immutable event timestamp.
        assert response.sort_mode == "asc"
        assert response.partition_keys == ["timestamp"]


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("forbidden", 403, False)])
    def test_maps_status_to_validity(self, _name: str, status: int, expected: bool) -> None:
        session = MagicMock()
        session.post.return_value = _ndjson_response([], status=status)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.coralogix.coralogix.make_tracked_session",
            return_value=session,
        ):
            assert validate_credentials("k", "coralogix.us") is expected
        assert session.post.call_args.args[0] == "https://api.coralogix.us/api/v1/dataprime/query"

    def test_network_error_is_invalid(self) -> None:
        session = MagicMock()
        session.post.side_effect = requests.ConnectionError("boom")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.coralogix.coralogix.make_tracked_session",
            return_value=session,
        ):
            assert validate_credentials("k", "coralogix.us") is False
