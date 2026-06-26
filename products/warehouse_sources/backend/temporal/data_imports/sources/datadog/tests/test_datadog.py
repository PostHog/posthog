from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.datadog import datadog as ddog
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.datadog import (
    DEFAULT_SITE,
    DatadogResumeConfig,
    _build_initial_params,
    _build_initial_url,
    _compute_next_url,
    _extract_items,
    _flatten_item,
    _format_datetime,
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

    def test_cursor_endpoint_first_sync_seeds_lookback_window(self) -> None:
        # No stored watermark, but the cursor endpoints must still send filter[from] so Datadog
        # doesn't fall back to its now-15m default.
        config = DATADOG_ENDPOINTS["logs"]
        params = _build_initial_params(config, should_use_incremental_field=True, db_incremental_field_last_value=None)
        assert params["filter[from]"].endswith("Z")


class TestBuildInitialUrl:
    def test_keeps_brackets_literal(self) -> None:
        config = DATADOG_ENDPOINTS["logs"]
        url = _build_initial_url("https://api.datadoghq.com", config, {"page[limit]": 1000})
        assert url == "https://api.datadoghq.com/api/v2/logs/events?page[limit]=1000"

    def test_no_params(self) -> None:
        config = DATADOG_ENDPOINTS["dashboards"]
        assert (
            _build_initial_url("https://api.datadoghq.com", config, {}) == "https://api.datadoghq.com/api/v1/dashboard"
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
        ],
    )
    def test_source_response_shape(self, endpoint: str, expected_pk: str, expect_partition: bool) -> None:
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
        assert response.primary_keys == [expected_pk]
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
