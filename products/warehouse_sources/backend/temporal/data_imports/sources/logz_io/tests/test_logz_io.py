import json
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.logz_io.logz_io import (
    LogzIOResumeConfig,
    _build_log_query,
    _parse_scroll_hits,
    base_url_for_region,
    get_rows,
    logz_io_source,
    validate_credentials,
)

TRANSPORT = "products.warehouse_sources.backend.temporal.data_imports.sources.logz_io.logz_io"


def _resp(json_body: Any, status: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = json_body
    resp.status_code = status
    resp.ok = status < 400
    return resp


def _make_manager(resume_state: LogzIOResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _scroll_response(scroll_id: str | None, hits: list[dict[str, Any]]) -> dict[str, Any]:
    # Logz.io returns `hits` as a JSON-encoded string wrapping the Elasticsearch hits structure.
    return {"scrollId": scroll_id, "hits": json.dumps({"total": len(hits), "hits": hits})}


def _hit(doc_id: str, source: dict[str, Any]) -> dict[str, Any]:
    return {"_id": doc_id, "_index": "logs-2026", "_source": source}


class TestBaseUrlForRegion:
    @pytest.mark.parametrize(
        "region, expected",
        [
            ("us", "https://api.logz.io"),
            ("eu", "https://api-eu.logz.io"),
            ("EU", "https://api-eu.logz.io"),
            ("uk", "https://api-uk.logz.io"),
            (None, "https://api.logz.io"),
            ("unknown", "https://api.logz.io"),
        ],
    )
    def test_base_url_for_region(self, region: str | None, expected: str) -> None:
        assert base_url_for_region(region) == expected


class TestParseScrollHits:
    def test_parses_stringified_hits_and_flattens_source(self) -> None:
        response = _scroll_response("s1", [_hit("a", {"@timestamp": "2026-07-01T00:00:00Z", "message": "hi"})])
        rows = _parse_scroll_hits(response)
        assert rows == [{"@timestamp": "2026-07-01T00:00:00Z", "message": "hi", "_id": "a", "_index": "logs-2026"}]

    def test_handles_hits_already_parsed_as_dict(self) -> None:
        response = {"scrollId": "s1", "hits": {"total": 1, "hits": [_hit("a", {"message": "hi"})]}}
        rows = _parse_scroll_hits(response)
        assert rows[0]["_id"] == "a"
        assert rows[0]["message"] == "hi"

    @pytest.mark.parametrize("response", [{}, {"hits": "not json"}, {"hits": None}, {"hits": {"hits": []}}])
    def test_missing_or_malformed_hits_yield_no_rows(self, response: dict[str, Any]) -> None:
        assert _parse_scroll_hits(response) == []


class TestBuildLogQuery:
    def test_incremental_uses_watermark_as_lower_bound(self) -> None:
        watermark = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
        query = _build_log_query(True, watermark, "@timestamp")
        range_filter = query["query"]["bool"]["filter"][0]["range"]["@timestamp"]
        assert range_filter["gte"] == "2026-07-01T12:00:00.000000Z"
        # Ascending sort so the pipeline can advance the watermark safely after each batch.
        assert query["sort"] == [{"@timestamp": {"order": "asc"}}]

    def test_first_sync_falls_back_to_a_bounded_lookback(self) -> None:
        # With no stored watermark the query must still be time-bounded, not an unbounded match-all.
        query = _build_log_query(True, None, "@timestamp")
        assert "gte" in query["query"]["bool"]["filter"][0]["range"]["@timestamp"]

    def test_honors_user_selected_incremental_field(self) -> None:
        query = _build_log_query(True, datetime(2026, 7, 1, tzinfo=UTC), "event_ts")
        assert "event_ts" in query["query"]["bool"]["filter"][0]["range"]
        assert query["sort"] == [{"event_ts": {"order": "asc"}}]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, schema_name, expected_valid",
        [
            (200, None, True),
            (401, None, False),
            # A missing scope at source-create is accepted — the token may only grant log access.
            (403, None, True),
            # ...but when checking a specific schema, a 403 means that table is unreachable.
            (403, "alerts", False),
            (500, None, False),
        ],
    )
    @mock.patch(f"{TRANSPORT}.make_tracked_session")
    def test_status_mapping(
        self, mock_session: mock.MagicMock, status_code: int, schema_name: str | None, expected_valid: bool
    ) -> None:
        mock_session.return_value.get.return_value = _resp({}, status=status_code)
        is_valid, _ = validate_credentials("token", "us", schema_name)
        assert is_valid is expected_valid

    @mock.patch(f"{TRANSPORT}.make_tracked_session")
    def test_network_error_is_not_valid(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        is_valid, message = validate_credentials("token", "us")
        assert is_valid is False
        assert message is not None

    @mock.patch(f"{TRANSPORT}.make_tracked_session")
    def test_eu_region_probes_eu_host(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _resp({}, status=200)
        validate_credentials("token", "eu")
        assert mock_session.return_value.get.call_args.args[0].startswith("https://api-eu.logz.io")

    @mock.patch(f"{TRANSPORT}.make_tracked_session")
    def test_token_registered_for_sample_redaction(self, mock_session: mock.MagicMock) -> None:
        # X-API-TOKEN isn't in the transport's auth-header denylist; dropping redact_values would
        # persist the raw token in captured HTTP samples, and following a redirect would replay the
        # token to another host.
        mock_session.return_value.get.return_value = _resp({}, status=200)
        validate_credentials("secret-token", "us")
        assert mock_session.call_args.kwargs["redact_values"] == ("secret-token",)
        assert mock_session.call_args.kwargs["allow_redirects"] is False


class TestSearchLogsScroll:
    @mock.patch(f"{TRANSPORT}.make_tracked_session")
    def test_walks_scroll_cursor_until_empty(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.side_effect = [
            _resp(_scroll_response("s1", [_hit("a", {"@timestamp": "t1"})])),
            _resp(_scroll_response("s2", [_hit("b", {"@timestamp": "t2"})])),
            _resp(_scroll_response("s2", [])),
        ]

        manager = _make_manager()
        rows = [r for batch in get_rows("token", "us", "search_logs", mock.MagicMock(), manager) for r in batch]

        assert [r["_id"] for r in rows] == ["a", "b"]
        # State is saved after each yielded batch that has a following cursor (never after the last).
        saved_ids = [c.args[0].scroll_id for c in manager.save_state.call_args_list]
        assert saved_ids == ["s1", "s2"]
        # The sync session must register the token for redaction and refuse redirects (X-API-TOKEN
        # isn't in the transport's auth-header denylist, so a redirect would leak it to another host).
        assert mock_session.call_args.kwargs["redact_values"] == ("token",)
        assert mock_session.call_args.kwargs["allow_redirects"] is False

    @mock.patch(f"{TRANSPORT}.make_tracked_session")
    def test_resumes_from_saved_scroll_cursor(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.side_effect = [
            _resp(_scroll_response("s9", [_hit("r", {"@timestamp": "t"})])),
            _resp(_scroll_response("s9", [])),
        ]

        manager = _make_manager(LogzIOResumeConfig(scroll_id="saved-cursor"))
        rows = [r for batch in get_rows("token", "us", "search_logs", mock.MagicMock(), manager) for r in batch]

        assert [r["_id"] for r in rows] == ["r"]
        # The first request continues the saved cursor rather than starting a fresh search.
        first_body = mock_session.return_value.request.call_args_list[0].kwargs["json"]
        assert first_body == {"scroll_id": "saved-cursor"}

    @mock.patch(f"{TRANSPORT}.make_tracked_session")
    def test_expired_cursor_restarts_search_from_watermark(self, mock_session: mock.MagicMock) -> None:
        expired = requests.HTTPError("400 scroll expired", response=mock.MagicMock())
        mock_session.return_value.request.side_effect = [
            expired,
            _resp(_scroll_response("s1", [_hit("a", {"@timestamp": "t"})])),
            _resp(_scroll_response("s1", [])),
        ]

        manager = _make_manager(LogzIOResumeConfig(scroll_id="stale"))
        rows = [r for batch in get_rows("token", "us", "search_logs", mock.MagicMock(), manager) for r in batch]

        assert [r["_id"] for r in rows] == ["a"]
        # After the stale cursor 400s, the restart posts the windowed search query, not the cursor.
        restart_body = mock_session.return_value.request.call_args_list[1].kwargs["json"]
        assert "query" in restart_body


class TestPagedEndpoints:
    @mock.patch(f"{TRANSPORT}.make_tracked_session")
    def test_walks_pages_until_short_page(self, mock_session: mock.MagicMock) -> None:
        full_page = [{"alertEventId": str(i)} for i in range(100)]
        mock_session.return_value.request.side_effect = [
            _resp({"results": full_page}),
            _resp({"results": [{"alertEventId": "100"}]}),
        ]

        manager = _make_manager()
        rows = [r for batch in get_rows("token", "us", "triggered_alerts", mock.MagicMock(), manager) for r in batch]

        assert len(rows) == 101
        page_numbers = [
            c.kwargs["json"]["pagination"]["pageNumber"] for c in mock_session.return_value.request.call_args_list
        ]
        assert page_numbers == [1, 2]

    @mock.patch(f"{TRANSPORT}.make_tracked_session")
    def test_empty_first_page_yields_nothing(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.return_value = _resp({"results": []})
        manager = _make_manager()
        assert list(get_rows("token", "us", "triggered_alerts", mock.MagicMock(), manager)) == []


class TestListEndpoints:
    @mock.patch(f"{TRANSPORT}.make_tracked_session")
    def test_bare_array_response_is_yielded(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.return_value = _resp([{"id": "1"}, {"id": "2"}])
        manager = _make_manager()
        rows = [r for batch in get_rows("token", "us", "alerts", mock.MagicMock(), manager) for r in batch]
        assert [r["id"] for r in rows] == ["1", "2"]


class TestSourceResponseShape:
    @pytest.mark.parametrize(
        "endpoint, primary_keys, partition_key",
        [
            ("search_logs", ["_id"], "@timestamp"),
            ("alerts", ["id"], "createdAt"),
            ("triggered_alerts", ["alertEventId"], "date"),
            ("notification_endpoints", ["id"], None),
        ],
    )
    def test_response_metadata_per_endpoint(
        self, endpoint: str, primary_keys: list[str], partition_key: str | None
    ) -> None:
        response = logz_io_source("token", "us", endpoint, mock.MagicMock(), _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "asc"
        if partition_key is None:
            assert response.partition_mode is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
