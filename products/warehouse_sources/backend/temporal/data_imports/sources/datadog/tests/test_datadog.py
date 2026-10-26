import dataclasses
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.datadog import (
    DEFAULT_SITE,
    DatadogFanOutLimitError,
    DatadogResumeConfig,
    DatadogRetryableError,
    _build_initial_params,
    _build_initial_url,
    _compute_next_url,
    _extract_items,
    _format_datetime,
    _format_filter_value,
    base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.settings import DATADOG_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.source import DatadogSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.datadog import (
    DatadogSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(
        DatadogSource(), DatadogSourceConfig(api_key="api", application_key="app", site="datadoghq.com")
    )


class TestBaseUrl:
    @pytest.mark.parametrize(
        ("site", "expected"),
        [
            ("datadoghq.com", "https://api.datadoghq.com"),
            ("datadoghq.eu", "https://api.datadoghq.eu"),
            ("ap1.datadoghq.com", "https://api.ap1.datadoghq.com"),
            # Unknown / spoofed hosts fall back to the default US site.
            ("evil.example.com", f"https://api.{DEFAULT_SITE}"),
            (None, f"https://api.{DEFAULT_SITE}"),
        ],
    )
    def test_base_url(self, site: Any, expected: str) -> None:
        assert base_url(site) == expected


class TestFormatDatetime:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("already-a-string", "already-a-string"),
        ],
    )
    def test_format_datetime(self, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestExtractItems:
    def test_top_level_list(self) -> None:
        config = DATADOG_ENDPOINTS["monitors"]  # data_path=None
        assert _extract_items([{"id": 1}, {"id": 2}], config) == [{"id": 1}, {"id": 2}]


class TestBuildInitialParams:
    @pytest.mark.parametrize(
        ("endpoint", "should_use_incremental_field", "last_value", "expected_present", "expected_absent"),
        [
            # Cursor endpoint, first sync / full refresh: page size + sort set, lookback seeds filter[from].
            (
                "logs",
                False,
                None,
                {"page[limit]": 1000, "sort": "timestamp"},
                [],
            ),
            # Error-only tables: the error filter is applied by Datadog, never after the fetch.
            (
                "error_spans",
                False,
                None,
                {"filter[query]": "status:error", "page[limit]": 1000, "sort": "timestamp"},
                [],
            ),
            (
                "error_logs",
                False,
                None,
                {"filter[query]": "status:error", "page[limit]": 1000, "sort": "timestamp"},
                [],
            ),
            (
                "error_spans",
                True,
                datetime(2026, 1, 1, tzinfo=UTC),
                {"filter[query]": "status:error", "filter[from]": "2026-01-01T00:00:00.000Z"},
                [],
            ),
            # Cursor endpoint, incremental continuation: filter[from] is the stored watermark.
            (
                "logs",
                True,
                datetime(2026, 1, 1, tzinfo=UTC),
                {"sort": "timestamp", "filter[from]": "2026-01-01T00:00:00.000Z"},
                [],
            ),
            # Full-refresh endpoint never sends a server-side time filter, even when incremental is on.
            (
                "monitors",
                True,
                datetime(2026, 1, 1, tzinfo=UTC),
                {"page": 0, "page_size": 100},
                ["filter[from]"],
            ),
            # Offset-paginated endpoint seeds offset + size at zero.
            (
                "incidents",
                False,
                None,
                {"page[offset]": 0, "page[size]": 100},
                ["filter[from]"],
            ),
            # Single-shot endpoint has no pagination or filter params.
            (
                "synthetic_tests",
                False,
                None,
                {},
                ["filter[from]", "sort"],
            ),
            # filter[product_families] is required and has no implicit default, so omitting it 400s.
            (
                "usage_hourly",
                False,
                None,
                {"filter[product_families]": "all", "page[limit]": 500},
                [],
            ),
            # The usage endpoints take hour- and month-precision cutoffs, not the ISO filter format.
            (
                "usage_hourly",
                True,
                datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                {"filter[timestamp][start]": "2026-03-04T02"},
                [],
            ),
            (
                "usage_summary",
                True,
                datetime(2026, 3, 4, tzinfo=UTC),
                {"start_month": "2026-03"},
                [],
            ),
        ],
    )
    def test_build_initial_params(
        self,
        endpoint: str,
        should_use_incremental_field: bool,
        last_value: Any,
        expected_present: dict[str, Any],
        expected_absent: list[str],
    ) -> None:
        config = DATADOG_ENDPOINTS[endpoint]
        params = _build_initial_params(
            config,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )

        for key, value in expected_present.items():
            assert params[key] == value
        for key in expected_absent:
            assert key not in params


class TestBuildInitialUrl:
    def test_no_params(self) -> None:
        assert (
            _build_initial_url("https://api.datadoghq.com", "/api/v1/dashboard", {})
            == "https://api.datadoghq.com/api/v1/dashboard"
        )


class TestComputeNextUrl:
    HOST = "https://api.datadoghq.com"

    @pytest.mark.parametrize(
        "next_link",
        [
            "https://evil.example.com/steal",  # off-host
            "http://api.datadoghq.com/api/v2/logs/events",  # non-https
            "https://api.datadoghq.com.evil.com/api/v2/logs/events",  # look-alike host
            "ftp://api.datadoghq.com/api/v2/logs/events",  # non-https scheme
        ],
    )
    def test_cursor_rejects_offhost_next(self, next_link: str) -> None:
        config = DATADOG_ENDPOINTS["logs"]
        assert (
            _compute_next_url(
                config,
                "https://api.datadoghq.com/api/v2/logs/events",
                {"links": {"next": next_link}},
                1000,
                self.HOST,
            )
            is None
        )

    def test_page_bumps_page_number(self) -> None:
        config = DATADOG_ENDPOINTS["monitors"]  # page_size=100
        nxt = _compute_next_url(
            config, "https://api.datadoghq.com/api/v1/monitor?page=0&page_size=100", {}, 100, self.HOST
        )
        assert nxt is not None
        query = parse_qs(urlparse(nxt).query)
        assert query["page"] == ["1"]

    def test_offset_advances_by_page_size(self) -> None:
        config = DATADOG_ENDPOINTS["incidents"]  # page_size=100
        nxt = _compute_next_url(
            config, "https://api.datadoghq.com/api/v2/incidents?page[offset]=0&page[size]=100", {}, 100, self.HOST
        )
        assert nxt is not None
        query = parse_qs(urlparse(nxt).query)
        assert query["page[offset]"] == ["100"]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            is_valid, error = validate_credentials("datadoghq.com", "api", "app")

        assert is_valid is expected_valid
        assert {request.path for request in network.requests_log} == {"/api/v1/validate"}
        assert network.requests_log[0].headers["dd-api-key"] == "api"
        assert network.requests_log[0].headers["dd-application-key"] == "app"
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    def test_request_exception_is_caught(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            is_valid, error = validate_credentials("datadoghq.com", "api", "app")

        assert is_valid is False
        assert error is not None
        assert {request.path for request in network.requests_log} == {"/api/v1/validate"}


class TestDatadogSourceResponse:
    @pytest.mark.parametrize(
        ("endpoint", "expected_pk", "expect_partition"),
        [
            ("logs", "id", True),
            ("monitors", "id", True),
            ("synthetic_tests", "public_id", False),
            ("slos", "id", False),
            # Composite keys: these grains have no single unique column.
            ("usage_hourly", ["public_id", "product_family", "timestamp"], True),
            ("usage_billable_summary", ["public_id", "start_date"], True),
            ("team_memberships", ["team_id", "id"], False),
            ("slo_history", ["slo_id", "from_ts"], False),
            ("metrics", ["metric"], False),
        ],
    )
    def test_source_response_shape(self, endpoint: str, expected_pk: Any, expect_partition: bool) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ([expected_pk] if isinstance(expected_pk, str) else expected_pk)
        assert response.sort_mode == "asc"
        if expect_partition:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [DATADOG_ENDPOINTS[endpoint].partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestGetRowsResume:
    def test_cursor_pagination_yields_and_saves_state(self) -> None:
        pages = [
            {
                "data": [{"id": "1", "attributes": {"timestamp": "t1"}}],
                "links": {"next": "https://api.datadoghq.com/p2"},
            },
            {"data": [{"id": "2", "attributes": {"timestamp": "t2"}}], "links": {}},
        ]
        result = _driver().run("logs", [ScriptedResponse(json=page) for page in pages])

        assert result.raised is None
        # Attributes flattened to root.
        assert result.items[0][0]["timestamp"] == "t1"
        assert result.items[1][0]["id"] == "2"
        # State saved after the first batch (before fetching page 2).
        assert result.saved_states == [DatadogResumeConfig(next_url="https://api.datadoghq.com/p2")]
        assert result.urls[1] == "https://api.datadoghq.com/p2"

    def test_resumes_from_saved_url(self) -> None:
        pages = [{"data": [{"id": "9", "attributes": {}}], "links": {}}]
        result = _driver().run(
            "logs",
            [ScriptedResponse(json=page) for page in pages],
            resume_state=DatadogResumeConfig(next_url="https://api.datadoghq.com/resume-here"),
        )
        assert result.raised is None
        assert result.urls[0] == "https://api.datadoghq.com/resume-here"

    @pytest.mark.parametrize(
        "resume_url",
        [
            "https://evil.example.com/steal",
            "http://api.datadoghq.com/resume-here",
            "https://api.datadoghq.com.evil.com/resume-here",
        ],
    )
    def test_tampered_resume_url_is_rejected(self, resume_url: str) -> None:
        result = _driver().run(
            "logs",
            [ScriptedResponse(json={"data": [{"id": "9", "attributes": {}}], "links": {}})],
            resume_state=DatadogResumeConfig(next_url=resume_url),
        )
        assert isinstance(result.raised, ValueError)
        assert "unexpected URL" in str(result.raised)
        assert result.requests == []


class TestFetchPageRetry:
    def test_408_is_retried_then_succeeds(self) -> None:
        result = _driver().run(
            "logs",
            [ScriptedResponse(status=408), ScriptedResponse(json={"data": [], "links": {}})],
        )
        assert result.raised is None
        assert result.paths == ["/api/v2/logs/events", "/api/v2/logs/events"]

    def test_persistent_408_reraises_as_retryable(self) -> None:
        result = _driver().run("logs", always(ScriptedResponse(status=408)))
        assert isinstance(result.raised, DatadogRetryableError)
        assert result.paths == ["/api/v2/logs/events"] * 5

    def test_other_4xx_is_not_retried(self) -> None:
        # A genuine client error stays fatal — HTTPError isn't retryable, so it never becomes
        # DatadogRetryableError. Guards against widening the 408 fix to swallow all 4xx.
        result = _driver().run("logs", [ScriptedResponse(status=400, body=b"400 body")])
        assert isinstance(result.raised, requests.HTTPError)
        assert result.paths == ["/api/v2/logs/events"]


class TestFormatFilterValue:
    def test_unparseable_string_falls_back_to_itself(self) -> None:
        assert _format_filter_value("not-a-date", "month") == "not-a-date"


class TestExtractItemsForNewShapes:
    def test_single_object_endpoint_rejects_a_list(self) -> None:
        config = DATADOG_ENDPOINTS["slo_history"]
        assert _extract_items({"data": [{"from_ts": 1}]}, config) == []

    def test_scalar_endpoint_wraps_each_name(self) -> None:
        config = DATADOG_ENDPOINTS["metrics"]
        assert _extract_items({"metrics": ["system.cpu.idle", "system.load.1"]}, config) == [
            {"metric": "system.cpu.idle"},
            {"metric": "system.load.1"},
        ]


class TestFanOut:
    def test_parent_deleted_mid_sync_is_skipped(self) -> None:
        # A 404 on one child must not fail the whole sync — the parent list is a snapshot.
        result = _driver().run(
            "slo_history",
            route(
                {
                    "/api/v1/slo": [ScriptedResponse(json={"data": [{"id": "gone"}, {"id": "slo-2"}]})],
                    "/api/v1/slo/gone/history": [ScriptedResponse(status=404)],
                    "/api/v1/slo/slo-2/history": [ScriptedResponse(json={"data": {"from_ts": 2}})],
                }
            ),
        )
        assert result.raised is None
        assert result.rows == [{"from_ts": 2, "slo_id": "slo-2"}]
        assert result.paths == ["/api/v1/slo", "/api/v1/slo/gone/history", "/api/v1/slo/slo-2/history"]

    def test_raises_when_the_parent_cap_is_exceeded(self) -> None:
        fan_out = DATADOG_ENDPOINTS["team_memberships"].parent
        assert fan_out is not None
        capped = dataclasses.replace(
            DATADOG_ENDPOINTS["team_memberships"],
            parent=dataclasses.replace(fan_out, max_parents=1),
        )
        # A truncated table that reports success would look like a complete sync.
        with mock.patch.dict(DATADOG_ENDPOINTS, {"team_memberships": capped}):
            result = _driver().run(
                "team_memberships",
                route(
                    {
                        "/api/v2/team": [ScriptedResponse(json={"data": [{"id": "team-a"}, {"id": "team-b"}]})],
                        "/api/v2/team/team-a/memberships": [ScriptedResponse(json={"data": [{"id": "m1"}]})],
                    }
                ),
            )
        assert isinstance(result.raised, DatadogFanOutLimitError)
        assert "team_memberships" in str(result.raised)
        assert result.paths == ["/api/v2/team", "/api/v2/team/team-a/memberships"]


class TestWalkTermination:
    def test_empty_page_with_a_cursor_keeps_paginating(self) -> None:
        # The usage cursor lives in meta, independently of data, so an empty page is not the end.
        result = _driver().run(
            "usage_hourly",
            [
                ScriptedResponse(json={"data": [], "meta": {"pagination": {"next_record_id": "rec-2"}}}),
                ScriptedResponse(json={"data": [{"id": "u2", "attributes": {}}], "meta": {"pagination": {}}}),
            ],
        )
        assert result.raised is None
        assert [batch[0]["id"] for batch in result.items] == ["u2"]
        assert len(result.requests) == 2
        assert result.params("page[next_record_id]") == [None, "rec-2"]
