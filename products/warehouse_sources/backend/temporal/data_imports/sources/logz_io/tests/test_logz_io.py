import json
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.logzio import LogzIOSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.logz_io.logz_io import (
    LogzIOResumeConfig,
    _build_log_query,
    _parse_scroll_hits,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.logz_io.source import LogzIOSource


def _driver() -> SourceDriver:
    return SourceDriver(LogzIOSource(), LogzIOSourceConfig(api_token="token", region="us"))


def _scroll_response(scroll_id: str | None, hits: list[dict[str, Any]]) -> dict[str, Any]:
    # Logz.io returns `hits` as a JSON-encoded string wrapping the Elasticsearch hits structure.
    return {"scrollId": scroll_id, "hits": json.dumps({"total": len(hits), "hits": hits})}


def _hit(doc_id: str, source: dict[str, Any]) -> dict[str, Any]:
    return {"_id": doc_id, "_index": "logs-2026", "_source": source}


class TestParseScrollHits:
    @pytest.mark.parametrize("response", [{}, {"hits": "not json"}, {"hits": None}, {"hits": {"hits": []}}])
    def test_missing_or_malformed_hits_yield_no_rows(self, response: dict[str, Any]) -> None:
        assert _parse_scroll_hits(response) == []


class TestBuildLogQuery:
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
    def test_status_mapping(self, status_code: int, schema_name: str | None, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            is_valid, _ = validate_credentials("token", "us", schema_name)

        assert is_valid is expected_valid
        assert network.requests_log[0].path == "/v2/alerts"

    def test_token_registered_for_sample_redaction(self) -> None:
        # X-API-TOKEN isn't in the transport's auth-header denylist; dropping redact_values would
        # persist the raw token in captured HTTP samples, and following a redirect would replay the
        # token to another host.
        with scripted_network([ScriptedResponse(status=200, json={})]) as network:
            validate_credentials("secret-token", "us")

        assert network.session_options[0]["redact_values"] == ("secret-token",)
        assert network.session_options[0]["allow_redirects"] is False


class TestSearchLogsScroll:
    def test_walks_scroll_cursor_until_empty(self) -> None:
        result = _driver().run(
            "search_logs",
            [
                ScriptedResponse(json=_scroll_response("s1", [_hit("a", {"@timestamp": "t1"})])),
                ScriptedResponse(json=_scroll_response("s2", [_hit("b", {"@timestamp": "t2"})])),
                ScriptedResponse(json=_scroll_response("s2", [])),
            ],
        )

        assert result.raised is None
        assert [r["_id"] for r in result.rows] == ["a", "b"]
        # State is saved after each yielded batch that has a following cursor (never after the last).
        assert result.saved_states == [LogzIOResumeConfig(scroll_id="s1"), LogzIOResumeConfig(scroll_id="s2")]
        # The sync session must register the token for redaction and refuse redirects (X-API-TOKEN
        # isn't in the transport's auth-header denylist, so a redirect would leak it to another host).
        assert result.session_options[0]["redact_values"] == ("token",)
        assert result.session_options[0]["allow_redirects"] is False

    def test_resumes_from_saved_scroll_cursor(self) -> None:
        result = _driver().run(
            "search_logs",
            [
                ScriptedResponse(json=_scroll_response("s9", [_hit("r", {"@timestamp": "t"})])),
                ScriptedResponse(json=_scroll_response("s9", [])),
            ],
            resume_state=LogzIOResumeConfig(scroll_id="saved-cursor"),
        )

        assert result.raised is None
        assert [r["_id"] for r in result.rows] == ["r"]
        # The first request continues the saved cursor rather than starting a fresh search.
        assert result.requests[0].json() == {"scroll_id": "saved-cursor"}

    def test_expired_cursor_restarts_search_from_watermark(self) -> None:
        result = _driver().run(
            "search_logs",
            [
                ScriptedResponse(status=400, json={}),
                ScriptedResponse(json=_scroll_response("s1", [_hit("a", {"@timestamp": "t"})])),
                ScriptedResponse(json=_scroll_response("s1", [])),
            ],
            resume_state=LogzIOResumeConfig(scroll_id="stale"),
        )

        assert result.raised is None
        assert [r["_id"] for r in result.rows] == ["a"]
        # After the stale cursor 400s, the restart posts the windowed search query, not the cursor.
        assert result.requests[0].json() == {"scroll_id": "stale"}
        assert "query" in result.requests[1].json()


class TestPagedEndpoints:
    def test_walks_pages_until_short_page(self) -> None:
        full_page = [{"alertEventId": str(i)} for i in range(100)]
        result = _driver().run(
            "triggered_alerts",
            [
                ScriptedResponse(json={"results": full_page}),
                ScriptedResponse(json={"results": [{"alertEventId": "100"}]}),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == 101
        assert [request.json()["pagination"]["pageNumber"] for request in result.requests] == [1, 2]

    def test_empty_first_page_yields_nothing(self) -> None:
        result = _driver().run("triggered_alerts", [ScriptedResponse(json={"results": []})])

        assert result.raised is None
        assert result.items == []


class TestOffsetEndpoints:
    def test_audit_trail_walks_offsets_and_derives_distinct_ids(self) -> None:
        full_page = [{"date": 1_700_000_000_000 + i, "auditEventTypeTitle": "Login"} for i in range(500)]
        result = _driver().run(
            "audit_trail",
            [
                ScriptedResponse(json={"results": full_page}),
                ScriptedResponse(json={"results": [{"date": 1_700_000_001_000, "auditEventTypeTitle": "Login"}]}),
            ],
        )

        assert result.raised is None
        assert len({row["audit_event_id"] for row in result.rows}) == 501
        assert [request.json()["from"] for request in result.requests] == [0, 500]


class TestIncrementalRequestShaping:
    @pytest.mark.parametrize(
        "endpoint, use_incremental, last_value, expected_fields",
        [
            (
                "security_events",
                True,
                1_780_000_000,
                {
                    "filter": {
                        "includeMutedEvents": True,
                        "timeRange": {"fromDate": 1_780_000_000, "toDate": 1_790_000_000},
                    },
                    "sort": [{"field": "DATE", "descending": False}],
                },
            ),
            (
                "security_events",
                False,
                None,
                {"filter": {"includeMutedEvents": True}, "sort": [{"field": "DATE", "descending": False}]},
            ),
            (
                "audit_trail",
                True,
                1_780_000_000_000,
                {"fromDate": 1_780_000_000_000, "toDate": 1_790_000_000_000, "sortDescending": False},
            ),
            # A watermark stored in seconds still reaches the API in milliseconds.
            (
                "audit_trail",
                True,
                1_780_000_000,
                {"fromDate": 1_780_000_000_000, "toDate": 1_790_000_000_000, "sortDescending": False},
            ),
        ],
    )
    @time_machine.travel(datetime.fromtimestamp(1_790_000_000, tz=UTC), tick=False)
    def test_time_range_in_request_body(
        self,
        endpoint: str,
        use_incremental: bool,
        last_value: int | None,
        expected_fields: dict[str, Any],
    ) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={"results": []})],
            should_use_incremental_field=use_incremental,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        body = result.requests[0].json()
        assert {key: body.get(key) for key in expected_fields} == expected_fields
        if not use_incremental:
            assert "timeRange" not in body["filter"]


class TestListEndpoints:
    def test_bare_array_response_is_yielded(self) -> None:
        result = _driver().run("alerts", [ScriptedResponse(json=[{"id": "1"}, {"id": "2"}])])

        assert result.raised is None
        assert [r["id"] for r in result.rows] == ["1", "2"]


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
        payload = {"hits": ""} if endpoint == "search_logs" else []
        result = _driver().run(endpoint, [ScriptedResponse(json=payload)])

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "asc"
        if partition_key is None:
            assert response.partition_mode is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
