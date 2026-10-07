import dataclasses
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog import datadog as ddog
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.datadog import (
    DEFAULT_SITE,
    DatadogFanOutLimitError,
    DatadogResumeConfig,
    DatadogRetryableError,
    _build_initial_params,
    _build_initial_url,
    _compute_next_url,
    _epoch_ms_to_iso,
    _extract_items,
    _flatten_item,
    _format_datetime,
    _format_filter_value,
    _join_included,
    base_url,
    datadog_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.settings import (
    DATADOG_ENDPOINTS,
    DatadogIssueSearchConfig,
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

    def test_unknown_endpoint_is_named_in_the_error(self) -> None:
        with pytest.raises(UnknownResourceError, match="not_a_table"):
            datadog_source(
                site="datadoghq.com",
                api_key="api",
                app_key="app",
                endpoint="not_a_table",
                logger=mock.MagicMock(),
                resumable_source_manager=mock.MagicMock(),
            )


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


class TestWalkPageCap:
    def test_max_pages_per_sync_stops_the_walk(self) -> None:
        # The error endpoints are rate limited, so a sync stops after a bounded number of pages and the
        # next one continues from the checkpointed cursor value.
        capped = dataclasses.replace(DATADOG_ENDPOINTS["error_logs"], max_pages_per_sync=2)
        bodies = [
            {"data": [{"id": str(i), "attributes": {}}], "links": {"next": f"https://api.datadoghq.com/p{i + 1}"}}
            for i in range(4)
        ]
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        manager.load_state.return_value = None
        fetched: list[str] = []

        def fake_get(url: str, timeout: Any = None) -> Any:
            resp = mock.MagicMock()
            resp.status_code = 200
            resp.ok = True
            resp.json.return_value = bodies[len(fetched)]
            fetched.append(url)
            return resp

        with (
            mock.patch.dict(DATADOG_ENDPOINTS, {"error_logs": capped}),
            mock.patch.object(ddog, "make_tracked_session") as mock_session,
        ):
            mock_session.return_value.get.side_effect = fake_get
            rows = list(
                ddog.get_rows(
                    site="datadoghq.com",
                    api_key="api",
                    app_key="app",
                    endpoint="error_logs",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                )
            )

        assert len(fetched) == 2
        assert [batch[0]["id"] for batch in rows] == ["0", "1"]


def _issue_result(issue_id: str, total: int, sessions: int = 1, users: int = 1) -> dict[str, Any]:
    return {
        "id": issue_id,
        "type": "error_tracking_search_result",
        "attributes": {"total_count": total, "impacted_sessions": sessions, "impacted_users": users},
        "relationships": {"issue": {"data": {"id": issue_id, "type": "issue"}}},
    }


def _issue_included(issue_id: str, last_seen: int, **attributes: Any) -> dict[str, Any]:
    return {
        "id": issue_id,
        "type": "issue",
        "attributes": {
            "error_type": "ConnectionError",
            "error_message": "Connection refused",
            "service": "checkout-api",
            "state": "OPEN",
            "first_seen": 1_772_593_094_123,
            "last_seen": last_seen,
            **attributes,
        },
    }


def _issue_response(*issues: tuple[str, int, int]) -> dict[str, Any]:
    """Build a search response from ``(issue id, total count, last_seen)`` tuples."""
    return {
        "data": [_issue_result(issue_id, total) for issue_id, total, _ in issues],
        "included": [_issue_included(issue_id, last_seen) for issue_id, _, last_seen in issues],
    }


class TestIssueSearch:
    def _run(self, responses: list[Any], config_override: Any = None) -> dict[str, Any]:
        """Run the issue sync against queued responses. An int is a bare HTTP status."""
        manager = mock.MagicMock()
        calls: list[dict[str, Any]] = []
        logger = mock.MagicMock()

        def fake_post(url: str, json: Any = None, timeout: Any = None) -> Any:
            calls.append({"url": url, "body": json})
            queued = responses[min(len(calls), len(responses)) - 1]
            resp = mock.MagicMock()
            resp.status_code = queued if isinstance(queued, int) else 200
            resp.ok = resp.status_code < 400
            resp.text = f"{resp.status_code} body"
            resp.json.return_value = {} if isinstance(queued, int) else queued
            if not resp.ok:
                resp.raise_for_status.side_effect = requests.HTTPError(
                    f"{resp.status_code} Client Error", response=resp
                )
            return resp

        endpoint_patch = {"error_tracking_issues": config_override} if config_override else {}
        with (
            mock.patch.dict(DATADOG_ENDPOINTS, endpoint_patch),
            mock.patch.object(ddog, "make_tracked_session") as mock_session,
            mock.patch("tenacity.nap.time.sleep"),
        ):
            mock_session.return_value.post.side_effect = fake_post
            rows = [
                row
                for batch in ddog.get_rows(
                    site="datadoghq.com",
                    api_key="api",
                    app_key="app",
                    endpoint="error_tracking_issues",
                    logger=logger,
                    resumable_source_manager=manager,
                )
                for row in batch
            ]
            get_called = mock_session.return_value.get.called

        return {"rows": rows, "calls": calls, "logger": logger, "get_called": get_called, "manager": manager}

    @staticmethod
    def _with_search(**overrides: Any) -> Any:
        base = DATADOG_ENDPOINTS["error_tracking_issues"]
        assert base.search is not None
        return dataclasses.replace(base, search=dataclasses.replace(base.search, **overrides))

    def test_posts_a_search_body_and_shapes_rows(self) -> None:
        result = self._run([_issue_response(("issue-1", 12, 1_772_679_494_000))])

        assert not result["get_called"]
        assert len(result["calls"]) == 1
        call = result["calls"][0]
        assert call["url"] == "https://api.datadoghq.com/api/v2/error-tracking/issues/search?include=issue"
        data = call["body"]["data"]
        assert data["type"] == "search_request"
        attributes = data["attributes"]
        assert attributes["persona"] == "ALL"
        assert isinstance(attributes["from"], int)
        assert isinstance(attributes["to"], int)
        assert attributes["from"] < attributes["to"]

        # Resolved and ignored issues never become signals, so Datadog is asked not to return them.
        assert attributes["states"] == ["OPEN", "ACKNOWLEDGED"]

        # Attributes the response omits are still present, so the table keeps the same columns.
        assert result["rows"] == [
            {
                **dict.fromkeys(DatadogIssueSearchConfig().issue_fields),
                "id": "issue-1",
                "error_type": "ConnectionError",
                "error_message": "Connection refused",
                "service": "checkout-api",
                "state": "OPEN",
                "first_seen": "2026-03-04T02:58:14.123Z",
                "last_seen": "2026-03-05T02:58:14.000Z",
                "window_total_count": 12,
                "window_impacted_sessions": 1,
                "window_impacted_users": 1,
            }
        ]
        # A sync must not leave resume state behind that a later run would pick up.
        result["manager"].save_state.assert_not_called()

    def test_full_response_halves_the_window_and_merges_by_issue(self) -> None:
        override = self._with_search(max_results_per_request=3)
        result = self._run(
            [
                # The whole window comes back full, so it may hide issues.
                _issue_response(("issue-1", 1, 1_000), ("issue-2", 1, 1_000), ("issue-3", 1, 1_000)),
                {
                    "data": [_issue_result("issue-1", 3, users=5), _issue_result("issue-2", 5)],
                    "included": [_issue_included("issue-1", 1_000), _issue_included("issue-2", 2_000)],
                },
                {
                    "data": [_issue_result("issue-1", 4, users=2)],
                    "included": [_issue_included("issue-1", 9_000)],
                },
            ],
            config_override=override,
        )

        whole, first, second = (call["body"]["data"]["attributes"] for call in result["calls"])
        assert len(result["calls"]) == 3
        # Earlier half first, and the halves tile the window with no gap or overlap.
        assert first["from"] == whole["from"]
        assert first["to"] == second["from"]
        assert second["to"] == whole["to"]

        by_id = {row["id"]: row for row in result["rows"]}
        assert set(by_id) == {"issue-1", "issue-2"}
        # Counts of the halves add up, and the full-window response is discarded, not double counted.
        assert by_id["issue-1"]["window_total_count"] == 7
        # A user can appear in both halves, so the distinct count is the larger half, not the sum.
        assert by_id["issue-1"]["window_impacted_users"] == 5
        assert by_id["issue-2"]["window_total_count"] == 5
        assert by_id["issue-1"]["last_seen"] == _epoch_ms_to_iso(9_000)

    def test_full_response_at_the_smallest_window_warns_and_keeps_rows(self) -> None:
        # Splitting stops at the minimum window. Dropping the rows silently would look like a
        # complete sync, so the cap is reported and the rows we got are kept.
        override = self._with_search(max_results_per_request=2, min_window_seconds=30 * 24 * 3600)
        result = self._run(
            [_issue_response(("issue-1", 1, 1_000), ("issue-2", 2, 1_000))],
            config_override=override,
        )

        assert len(result["calls"]) == 1
        assert {row["id"] for row in result["rows"]} == {"issue-1", "issue-2"}
        result["logger"].warning.assert_called_once()
        assert "smallest window" in result["logger"].warning.call_args.args[0]

    def test_request_cap_stops_splitting_and_warns(self) -> None:
        # Every response is full, so an unbounded sync would split down to the smallest window.
        override = self._with_search(max_results_per_request=1, max_requests_per_sync=5)
        result = self._run([_issue_response(("issue-1", 1, 1_000))], config_override=override)

        assert len(result["calls"]) <= 5
        assert {row["id"] for row in result["rows"]} == {"issue-1"}
        assert any("limit of 5 requests" in call.args[0] for call in result["logger"].warning.call_args_list)

    @pytest.mark.parametrize(
        ("statuses", "expected_calls"),
        [
            ([408, 200], 2),
            ([429, 200], 2),
            ([503, 200], 2),
        ],
    )
    def test_transient_statuses_are_retried_on_post(self, statuses: list[int], expected_calls: int) -> None:
        # The transport retries only GET, so the POST search depends on the retry in fetch_page.
        result = self._run([*statuses[:-1], _issue_response(("issue-1", 1, 1_000))])
        assert len(result["calls"]) == expected_calls
        assert [row["id"] for row in result["rows"]] == ["issue-1"]

    def test_missing_scope_is_not_retried(self) -> None:
        with pytest.raises(requests.HTTPError, match="403"):
            self._run([403, 403])


_SEEDED = dict.fromkeys(DatadogIssueSearchConfig().issue_fields)


class TestJoinIncluded:
    SEARCH = DatadogIssueSearchConfig()

    @pytest.mark.parametrize(
        ("response", "expected"),
        [
            # No ``included`` at all: the row keeps its id and counts.
            (
                {"data": [_issue_result("issue-1", 4)]},
                [
                    {
                        **_SEEDED,
                        "id": "issue-1",
                        "window_total_count": 4,
                        "window_impacted_sessions": 1,
                        "window_impacted_users": 1,
                    }
                ],
            ),
            # No relationship: the result id is the issue id.
            (
                {
                    "data": [{"id": "issue-1", "attributes": {"total_count": 2}}],
                    "included": [_issue_included("issue-1", 5, error_type="TimeoutError")],
                },
                [
                    {
                        **_SEEDED,
                        "id": "issue-1",
                        "error_type": "TimeoutError",
                        "error_message": "Connection refused",
                        "service": "checkout-api",
                        "state": "OPEN",
                        "first_seen": 1_772_593_094_123,
                        "last_seen": 5,
                        "window_total_count": 2,
                        "window_impacted_sessions": None,
                        "window_impacted_users": None,
                    }
                ],
            ),
            # Null attributes on both sides must not raise.
            (
                {
                    "data": [{"id": "issue-1", "attributes": None, "relationships": None}],
                    "included": [{"id": "issue-1", "type": "issue", "attributes": None}],
                },
                [
                    {
                        **_SEEDED,
                        "id": "issue-1",
                        "window_total_count": None,
                        "window_impacted_sessions": None,
                        "window_impacted_users": None,
                    }
                ],
            ),
            # Only issue objects supply attributes; a case or team that reuses the id must not leak in.
            (
                {
                    "data": [_issue_result("issue-1", 1)],
                    "included": [
                        {"id": "issue-1", "type": "case", "attributes": {"title": "Not an issue"}},
                        _issue_included("issue-1", 5, error_type="TimeoutError"),
                    ],
                },
                [
                    {
                        **_SEEDED,
                        "id": "issue-1",
                        "error_type": "TimeoutError",
                        "error_message": "Connection refused",
                        "service": "checkout-api",
                        "state": "OPEN",
                        "first_seen": 1_772_593_094_123,
                        "last_seen": 5,
                        "window_total_count": 1,
                        "window_impacted_sessions": 1,
                        "window_impacted_users": 1,
                    }
                ],
            ),
            ("not a dict", []),
        ],
    )
    def test_join_edge_cases(self, response: Any, expected: Any) -> None:
        assert _join_included(response, self.SEARCH) == expected


class TestEpochMsToIso:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1_772_593_094_123, "2026-03-04T02:58:14.123Z"),
            (1_772_593_094_000, "2026-03-04T02:58:14.000Z"),
            (1_772_593_094_123.0, "2026-03-04T02:58:14.123Z"),
            (None, None),
            ("2026-03-04T02:58:14.123Z", "2026-03-04T02:58:14.123Z"),
            (True, True),
        ],
    )
    def test_epoch_ms_to_iso(self, value: Any, expected: Any) -> None:
        assert _epoch_ms_to_iso(value) == expected
