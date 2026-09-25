import dataclasses
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.datadog import datadog as ddog
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.datadog import (
    DEFAULT_SITE,
    DatadogFanOutLimitError,
    DatadogResumeConfig,
    DatadogRetryableError,
    _build_initial_params,
    _build_initial_url,
    _compute_next_url,
    _extract_items,
    _flatten_item,
    _format_datetime,
    _format_filter_value,
    base_url,
    datadog_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.settings import DATADOG_ENDPOINTS


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

    def test_no_plus_zero_offset(self) -> None:
        assert "+00:00" not in _format_datetime(datetime(2026, 3, 4, tzinfo=UTC))


class TestExtractItems:
    def test_top_level_list(self) -> None:
        config = DATADOG_ENDPOINTS["monitors"]  # data_path=None
        assert _extract_items([{"id": 1}, {"id": 2}], config) == [{"id": 1}, {"id": 2}]

    def test_top_level_list_with_unexpected_dict(self) -> None:
        config = DATADOG_ENDPOINTS["monitors"]
        assert _extract_items({"unexpected": "shape"}, config) == []

    def test_wrapped_data_path(self) -> None:
        config = DATADOG_ENDPOINTS["logs"]  # data_path="data"
        assert _extract_items({"data": [{"id": "a"}]}, config) == [{"id": "a"}]

    def test_wrapped_custom_path(self) -> None:
        config = DATADOG_ENDPOINTS["dashboards"]  # data_path="dashboards"
        assert _extract_items({"dashboards": [{"id": "x"}]}, config) == [{"id": "x"}]

    def test_missing_path_returns_empty(self) -> None:
        config = DATADOG_ENDPOINTS["logs"]
        assert _extract_items({"meta": {}}, config) == []


class TestFlattenItem:
    def test_flattens_attributes_to_root(self) -> None:
        item = {"id": "abc", "type": "log", "attributes": {"timestamp": "2026-01-01T00:00:00Z", "status": "info"}}
        flat = _flatten_item(item)
        assert flat["id"] == "abc"
        assert flat["type"] == "log"
        assert flat["timestamp"] == "2026-01-01T00:00:00Z"
        assert flat["status"] == "info"
        assert "attributes" not in flat

    def test_does_not_clobber_existing_root_keys(self) -> None:
        item = {"id": "abc", "attributes": {"id": "SHOULD_NOT_WIN", "name": "x"}}
        flat = _flatten_item(item)
        assert flat["id"] == "abc"
        assert flat["name"] == "x"

    def test_no_attributes_is_noop(self) -> None:
        item = {"id": "abc", "name": "x"}
        assert _flatten_item(item) == {"id": "abc", "name": "x"}


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

    def test_full_refresh_ignores_a_stored_watermark(self) -> None:
        params = _build_initial_params(
            DATADOG_ENDPOINTS["usage_hourly"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params["filter[timestamp][start]"] != "2026-03-04T00"

    def test_cursor_endpoint_first_sync_seeds_lookback_window(self) -> None:
        # No stored watermark, but the cursor endpoints must still send filter[from] so Datadog
        # doesn't fall back to its now-15m default.
        config = DATADOG_ENDPOINTS["logs"]
        params = _build_initial_params(config, should_use_incremental_field=True, db_incremental_field_last_value=None)
        assert params["filter[from]"].endswith("Z")


class TestBuildInitialUrl:
    def test_keeps_brackets_literal(self) -> None:
        url = _build_initial_url("https://api.datadoghq.com", "/api/v2/logs/events", {"page[limit]": 1000})
        assert url == "https://api.datadoghq.com/api/v2/logs/events?page[limit]=1000"

    def test_no_params(self) -> None:
        assert (
            _build_initial_url("https://api.datadoghq.com", "/api/v1/dashboard", {})
            == "https://api.datadoghq.com/api/v1/dashboard"
        )


class TestComputeNextUrl:
    HOST = "https://api.datadoghq.com"

    def test_cursor_uses_links_next(self) -> None:
        config = DATADOG_ENDPOINTS["logs"]
        nxt = _compute_next_url(
            config,
            "https://api.datadoghq.com/api/v2/logs/events",
            {"links": {"next": "https://api.datadoghq.com/api/v2/logs/events?cursor=abc"}},
            1000,
            self.HOST,
        )
        assert nxt == "https://api.datadoghq.com/api/v2/logs/events?cursor=abc"

    def test_cursor_no_links_terminates(self) -> None:
        config = DATADOG_ENDPOINTS["logs"]
        assert (
            _compute_next_url(config, "https://api.datadoghq.com/api/v2/logs/events", {"data": []}, 0, self.HOST)
            is None
        )

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

    def test_page_short_page_terminates(self) -> None:
        config = DATADOG_ENDPOINTS["monitors"]
        nxt = _compute_next_url(
            config, "https://api.datadoghq.com/api/v1/monitor?page=0&page_size=100", {}, 42, self.HOST
        )
        assert nxt is None

    def test_offset_advances_by_page_size(self) -> None:
        config = DATADOG_ENDPOINTS["incidents"]  # page_size=100
        nxt = _compute_next_url(
            config, "https://api.datadoghq.com/api/v2/incidents?page[offset]=0&page[size]=100", {}, 100, self.HOST
        )
        assert nxt is not None
        query = parse_qs(urlparse(nxt).query)
        assert query["page[offset]"] == ["100"]

    def test_offset_short_page_terminates(self) -> None:
        config = DATADOG_ENDPOINTS["incidents"]
        nxt = _compute_next_url(
            config, "https://api.datadoghq.com/api/v2/incidents?page[offset]=0&page[size]=100", {}, 7, self.HOST
        )
        assert nxt is None

    def test_advances_with_the_record_cursor(self) -> None:
        config = DATADOG_ENDPOINTS["usage_hourly"]
        nxt = _compute_next_url(
            config,
            "https://api.datadoghq.com/api/v2/usage/hourly_usage?page[limit]=500",
            {"meta": {"pagination": {"next_record_id": "rec-2"}}},
            500,
            self.HOST,
        )
        assert nxt is not None
        query = parse_qs(urlparse(nxt).query)
        assert query["page[next_record_id]"] == ["rec-2"]
        assert query["page[limit]"] == ["500"]

    @pytest.mark.parametrize(
        "body",
        [
            {"meta": {"pagination": {"next_record_id": None}}},
            {"meta": {"pagination": {}}},
            {"meta": {}},
            {},
        ],
    )
    def test_absent_cursor_terminates(self, body: Any) -> None:
        config = DATADOG_ENDPOINTS["usage_hourly"]
        assert (
            _compute_next_url(config, "https://api.datadoghq.com/api/v2/usage/hourly_usage", body, 500, self.HOST)
            is None
        )

    def test_short_page_does_not_terminate(self) -> None:
        # The record cursor is the only termination signal here — a short page is normal.
        config = DATADOG_ENDPOINTS["usage_hourly"]
        nxt = _compute_next_url(
            config,
            "https://api.datadoghq.com/api/v2/usage/hourly_usage?page[limit]=500",
            {"meta": {"pagination": {"next_record_id": "rec-2"}}},
            3,
            self.HOST,
        )
        assert nxt is not None

    def test_none_pagination_terminates(self) -> None:
        config = DATADOG_ENDPOINTS["dashboards"]
        assert (
            _compute_next_url(
                config, "https://api.datadoghq.com/api/v1/dashboard", {"dashboards": [1, 2]}, 2, self.HOST
            )
            is None
        )


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.datadog.datadog.make_tracked_session")
    def test_status_mapping(self, mock_session: mock.MagicMock, status_code: int, expected_valid: bool) -> None:
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        is_valid, error = validate_credentials("datadoghq.com", "api", "app")

        assert is_valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.datadog.datadog.make_tracked_session")
    def test_request_exception_is_caught(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
        is_valid, error = validate_credentials("datadoghq.com", "api", "app")
        assert is_valid is False
        assert error is not None


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
        manager = mock.MagicMock()
        response = datadog_source(
            site="datadoghq.com",
            api_key="api",
            app_key="app",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=manager,
        )
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
    def _run(
        self, endpoint: str, pages: list[Any], can_resume: bool, resume_url: str | None
    ) -> tuple[list[Any], list[str], list[str]]:
        manager = mock.MagicMock()
        manager.can_resume.return_value = can_resume
        manager.load_state.return_value = DatadogResumeConfig(next_url=resume_url) if resume_url else None
        saved: list[str] = []
        manager.save_state.side_effect = lambda state: saved.append(state.next_url)

        fetched_urls: list[str] = []

        def fake_get(url: str, headers: Any = None, timeout: Any = None) -> Any:
            fetched_urls.append(url)
            resp = mock.MagicMock()
            resp.status_code = 200
            resp.ok = True
            resp.json.return_value = pages[len(fetched_urls) - 1]
            return resp

        with mock.patch.object(ddog, "make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = fake_get
            rows = list(
                ddog.get_rows(
                    site="datadoghq.com",
                    api_key="api",
                    app_key="app",
                    endpoint=endpoint,
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                )
            )
        return rows, saved, fetched_urls

    def test_cursor_pagination_yields_and_saves_state(self) -> None:
        pages = [
            {
                "data": [{"id": "1", "attributes": {"timestamp": "t1"}}],
                "links": {"next": "https://api.datadoghq.com/p2"},
            },
            {"data": [{"id": "2", "attributes": {"timestamp": "t2"}}], "links": {}},
        ]
        rows, saved, fetched = self._run("logs", pages, can_resume=False, resume_url=None)

        # Attributes flattened to root.
        assert rows[0][0]["timestamp"] == "t1"
        assert rows[1][0]["id"] == "2"
        # State saved after the first batch (before fetching page 2).
        assert saved == ["https://api.datadoghq.com/p2"]
        assert fetched[1] == "https://api.datadoghq.com/p2"

    def test_resumes_from_saved_url(self) -> None:
        pages = [{"data": [{"id": "9", "attributes": {}}], "links": {}}]
        _rows, _saved, fetched = self._run(
            "logs", pages, can_resume=True, resume_url="https://api.datadoghq.com/resume-here"
        )
        assert fetched[0] == "https://api.datadoghq.com/resume-here"

    @pytest.mark.parametrize(
        "resume_url",
        [
            "https://evil.example.com/steal",
            "http://api.datadoghq.com/resume-here",
            "https://api.datadoghq.com.evil.com/resume-here",
        ],
    )
    def test_tampered_resume_url_is_rejected(self, resume_url: str) -> None:
        pages = [{"data": [{"id": "9", "attributes": {}}], "links": {}}]
        with pytest.raises(ValueError, match="unexpected URL"):
            self._run("logs", pages, can_resume=True, resume_url=resume_url)


class TestFetchPageRetry:
    def _run(self, statuses: list[int]) -> list[int]:
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        manager.load_state.return_value = None

        seen: list[int] = []

        def fake_get(url: str, headers: Any = None, timeout: Any = None) -> Any:
            status = statuses[len(seen)]
            seen.append(status)
            resp = mock.MagicMock()
            resp.status_code = status
            resp.ok = status < 400
            resp.json.return_value = {"data": [], "links": {}}
            resp.text = f"{status} body"
            if status >= 400:
                resp.raise_for_status.side_effect = requests.HTTPError(f"{status} Client Error", response=resp)
            return resp

        # Patch tenacity's backoff sleep so retries don't block the test.
        with (
            mock.patch.object(ddog, "make_tracked_session") as mock_session,
            mock.patch("tenacity.nap.time.sleep"),
        ):
            mock_session.return_value.get.side_effect = fake_get
            list(
                ddog.get_rows(
                    site="datadoghq.com",
                    api_key="api",
                    app_key="app",
                    endpoint="logs",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                )
            )
        return seen

    def test_408_is_retried_then_succeeds(self) -> None:
        seen = self._run([408, 200])
        assert seen == [408, 200]

    def test_persistent_408_reraises_as_retryable(self) -> None:
        with pytest.raises(DatadogRetryableError):
            self._run([408, 408, 408, 408, 408])

    def test_other_4xx_is_not_retried(self) -> None:
        # A genuine client error stays fatal — HTTPError isn't retryable, so it never becomes
        # DatadogRetryableError. Guards against widening the 408 fix to swallow all 4xx.
        with pytest.raises(requests.HTTPError):
            self._run([400])


class TestFormatFilterValue:
    @pytest.mark.parametrize(
        ("timestamp_format", "expected"),
        [
            ("iso_ms", "2026-03-04T02:58:14.000Z"),
            ("month", "2026-03"),
            ("hour", "2026-03-04T02"),
            ("epoch_seconds", "1772593094"),
        ],
    )
    def test_each_family_encoding(self, timestamp_format: Any, expected: str) -> None:
        assert _format_filter_value(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), timestamp_format) == expected

    @pytest.mark.parametrize("timestamp_format", ["month", "hour", "epoch_seconds"])
    def test_iso_string_watermark_is_parsed(self, timestamp_format: Any) -> None:
        # A string watermark can pass straight through an ISO filter but would be rejected by the
        # month / hour / epoch filters, so it has to be parsed rather than forwarded.
        value = _format_filter_value("2026-03-04T02:58:14Z", timestamp_format)
        assert value != "2026-03-04T02:58:14Z"
        assert _format_filter_value(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), timestamp_format) == value

    def test_unparseable_string_falls_back_to_itself(self) -> None:
        assert _format_filter_value("not-a-date", "month") == "not-a-date"


class TestExtractItemsForNewShapes:
    def test_single_object_endpoint_wraps_the_object(self) -> None:
        config = DATADOG_ENDPOINTS["slo_history"]
        assert _extract_items({"data": {"from_ts": 1, "type": "metric"}}, config) == [{"from_ts": 1, "type": "metric"}]

    def test_single_object_endpoint_rejects_a_list(self) -> None:
        config = DATADOG_ENDPOINTS["slo_history"]
        assert _extract_items({"data": [{"from_ts": 1}]}, config) == []

    def test_scalar_endpoint_wraps_each_name(self) -> None:
        config = DATADOG_ENDPOINTS["metrics"]
        assert _extract_items({"metrics": ["system.cpu.idle", "system.load.1"]}, config) == [
            {"metric": "system.cpu.idle"},
            {"metric": "system.load.1"},
        ]


class TestWindowedEndpointParams:
    def test_sends_both_bounds_in_epoch_seconds(self) -> None:
        # /api/v1/slo/{slo_id}/history rejects a request missing either bound.
        params = _build_initial_params(
            DATADOG_ENDPOINTS["slo_history"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert int(params["from_ts"]) < int(params["to_ts"])


class TestFanOut:
    def _run(self, endpoint: str, bodies: dict[str, Any], statuses: dict[str, int] | None = None) -> dict[str, Any]:
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        manager.load_state.return_value = None
        saved: list[str] = []
        manager.save_state.side_effect = lambda state: saved.append(state.next_url)

        requested: list[str] = []

        def fake_get(url: str, timeout: Any = None) -> Any:
            requested.append(url)
            path = urlparse(url).path
            resp = mock.MagicMock()
            resp.status_code = (statuses or {}).get(path, 200)
            resp.ok = resp.status_code < 400
            resp.text = "body"
            resp.json.return_value = bodies.get(path, {})
            if not resp.ok:
                resp.raise_for_status.side_effect = requests.HTTPError("error", response=resp)
            return resp

        with mock.patch.object(ddog, "make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = fake_get
            rows = [row for batch in self._rows(endpoint, manager) for row in batch]

        return {"rows": rows, "saved": saved, "paths": [urlparse(u).path for u in requested]}

    def _rows(self, endpoint: str, manager: Any) -> Any:
        return ddog.get_rows(
            site="datadoghq.com",
            api_key="api",
            app_key="app",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=manager,
        )

    def test_queries_each_parent_and_stamps_the_parent_id(self) -> None:
        result = self._run(
            "team_memberships",
            {
                "/api/v2/team": {"data": [{"id": "team-a", "attributes": {}}, {"id": "team-b", "attributes": {}}]},
                "/api/v2/team/team-a/memberships": {"data": [{"id": "m1", "attributes": {"role": "admin"}}]},
                "/api/v2/team/team-b/memberships": {"data": [{"id": "m2", "attributes": {"role": "member"}}]},
            },
        )

        assert result["rows"] == [
            {"id": "m1", "role": "admin", "team_id": "team-a"},
            {"id": "m2", "role": "member", "team_id": "team-b"},
        ]
        assert "/api/v2/team/team-a/memberships" in result["paths"]
        assert "/api/v2/team/team-b/memberships" in result["paths"]

    def test_single_object_child_is_yielded_as_one_row(self) -> None:
        result = self._run(
            "slo_history",
            {
                "/api/v1/slo": {"data": [{"id": "slo-1"}]},
                "/api/v1/slo/slo-1/history": {"data": {"from_ts": 1, "overall": {"sli_value": 99.9}}},
            },
        )
        assert result["rows"] == [{"from_ts": 1, "overall": {"sli_value": 99.9}, "slo_id": "slo-1"}]

    def test_parent_deleted_mid_sync_is_skipped(self) -> None:
        # A 404 on one child must not fail the whole sync — the parent list is a snapshot.
        result = self._run(
            "slo_history",
            {
                "/api/v1/slo": {"data": [{"id": "gone"}, {"id": "slo-2"}]},
                "/api/v1/slo/slo-2/history": {"data": {"from_ts": 2}},
            },
            statuses={"/api/v1/slo/gone/history": 404},
        )
        assert result["rows"] == [{"from_ts": 2, "slo_id": "slo-2"}]

    def test_raises_when_the_parent_cap_is_exceeded(self) -> None:
        fan_out = DATADOG_ENDPOINTS["team_memberships"].parent
        assert fan_out is not None
        capped = dataclasses.replace(
            DATADOG_ENDPOINTS["team_memberships"],
            parent=dataclasses.replace(fan_out, max_parents=1),
        )
        # A truncated table that reports success would look like a complete sync.
        with mock.patch.dict(DATADOG_ENDPOINTS, {"team_memberships": capped}):
            with pytest.raises(DatadogFanOutLimitError, match="team_memberships"):
                self._run(
                    "team_memberships",
                    {
                        "/api/v2/team": {"data": [{"id": "team-a"}, {"id": "team-b"}]},
                        "/api/v2/team/team-a/memberships": {"data": [{"id": "m1"}]},
                        "/api/v2/team/team-b/memberships": {"data": [{"id": "m2"}]},
                    },
                )

    def test_no_resume_state_is_saved(self) -> None:
        # A fan-out position is a parent cursor plus a child page, which the single-URL resume
        # state can't express — saving one would resume the child walk against the wrong parent.
        result = self._run(
            "team_memberships",
            {
                "/api/v2/team": {"data": [{"id": "team-a"}]},
                "/api/v2/team/team-a/memberships": {"data": [{"id": "m1"}]},
            },
        )
        assert result["saved"] == []


class TestWalkTermination:
    def _pages(self, endpoint: str, bodies: list[Any]) -> tuple[list[Any], list[str]]:
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        manager.load_state.return_value = None
        fetched: list[str] = []

        def fake_get(url: str, timeout: Any = None) -> Any:
            resp = mock.MagicMock()
            resp.status_code = 200
            resp.ok = True
            resp.json.return_value = bodies[min(len(fetched), len(bodies) - 1)]
            fetched.append(url)
            return resp

        with mock.patch.object(ddog, "make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = fake_get
            rows = list(
                ddog.get_rows(
                    site="datadoghq.com",
                    api_key="api",
                    app_key="app",
                    endpoint=endpoint,
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                )
            )
        return rows, fetched

    def test_repeated_record_cursor_stops_the_walk(self) -> None:
        # Datadog echoing the same cursor would otherwise loop this walk forever.
        rows, fetched = self._pages(
            "usage_hourly",
            [{"data": [{"id": "u1", "attributes": {}}], "meta": {"pagination": {"next_record_id": "same"}}}],
        )
        assert len(fetched) == 2
        assert len(rows) == 2

    def test_empty_page_with_a_cursor_keeps_paginating(self) -> None:
        # The usage cursor lives in meta, independently of data, so an empty page is not the end.
        rows, fetched = self._pages(
            "usage_hourly",
            [
                {"data": [], "meta": {"pagination": {"next_record_id": "rec-2"}}},
                {"data": [{"id": "u2", "attributes": {}}], "meta": {"pagination": {}}},
            ],
        )
        assert [batch[0]["id"] for batch in rows] == ["u2"]
        assert len(fetched) == 2
