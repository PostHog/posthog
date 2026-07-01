from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost import sparkpost as sp
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.settings import SPARKPOST_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.sparkpost import (
    DEFAULT_REGION,
    SparkPostResumeConfig,
    _build_initial_params,
    _build_initial_url,
    _compute_next_url,
    _extract_items,
    _format_from,
    base_url,
    sparkpost_source,
    validate_credentials,
)


class TestBaseUrl:
    @pytest.mark.parametrize(
        ("region", "expected"),
        [
            ("us", "https://api.sparkpost.com"),
            ("eu", "https://api.eu.sparkpost.com"),
            ("US", "https://api.sparkpost.com"),
            # Unknown / spoofed regions fall back to the default US host.
            ("evil", "https://api.sparkpost.com"),
            (None, "https://api.sparkpost.com"),
        ],
    )
    def test_base_url(self, region: Any, expected: str) -> None:
        assert base_url(region) == expected

    def test_default_region_is_us(self) -> None:
        assert DEFAULT_REGION == "us"


class TestFormatFrom:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58"),
            # Truncated to the minute; seconds dropped.
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30"),
            # Naive datetimes are treated as UTC.
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58"),
            (date(2026, 3, 4), "2026-03-04T00:00"),
            # ISO 8601 strings (how the stored watermark can come back) are parsed, not passed
            # through — SparkPost rejects a raw ``...T00:00:00Z`` value.
            ("2026-01-01T00:00:00Z", "2026-01-01T00:00"),
            ("2026-01-15T10:30:45.123456Z", "2026-01-15T10:30"),
            ("2026-03-04T02:58:14+00:00", "2026-03-04T02:58"),
            # A genuinely unparseable string still falls through unchanged.
            ("already-a-string", "already-a-string"),
        ],
    )
    def test_format_from(self, value: Any, expected: str) -> None:
        assert _format_from(value) == expected

    def test_no_timezone_offset_in_output(self) -> None:
        assert "+00:00" not in _format_from(datetime(2026, 3, 4, tzinfo=UTC))


class TestExtractItems:
    def test_wrapped_results(self) -> None:
        config = SPARKPOST_ENDPOINTS["events"]
        assert _extract_items({"results": [{"event_id": "1"}]}, config) == [{"event_id": "1"}]

    def test_missing_results_returns_empty(self) -> None:
        config = SPARKPOST_ENDPOINTS["events"]
        assert _extract_items({"total_count": 0}, config) == []

    def test_non_dict_returns_empty(self) -> None:
        config = SPARKPOST_ENDPOINTS["events"]
        assert _extract_items([{"event_id": "1"}], config) == []

    def test_results_not_a_list_returns_empty(self) -> None:
        config = SPARKPOST_ENDPOINTS["events"]
        assert _extract_items({"results": {"unexpected": "shape"}}, config) == []


class TestBuildInitialParams:
    def test_cursor_endpoint_seeds_cursor_and_per_page(self) -> None:
        config = SPARKPOST_ENDPOINTS["events"]
        params = _build_initial_params(config, should_use_incremental_field=False, db_incremental_field_last_value=None)
        assert params["cursor"] == "initial"
        assert params["per_page"] == config.per_page

    def test_non_cursor_endpoint_has_no_pagination_params(self) -> None:
        config = SPARKPOST_ENDPOINTS["templates"]
        params = _build_initial_params(config, should_use_incremental_field=False, db_incremental_field_last_value=None)
        assert "cursor" not in params
        assert "per_page" not in params
        assert "from" not in params

    def test_events_incremental_uses_stored_watermark(self) -> None:
        config = SPARKPOST_ENDPOINTS["events"]
        params = _build_initial_params(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, 12, 30, tzinfo=UTC),
        )
        assert params["from"] == "2026-01-01T12:30"

    def test_events_first_sync_seeds_lookback_window(self) -> None:
        # No stored watermark: ``from`` is seeded from the 10-day retention lookback so the first
        # sync doesn't fall back to SparkPost's default short window.
        config = SPARKPOST_ENDPOINTS["events"]
        params = _build_initial_params(config, should_use_incremental_field=True, db_incremental_field_last_value=None)
        assert "from" in params

    def test_full_refresh_endpoint_never_sends_time_filter(self) -> None:
        # Even with incremental on, a full-refresh endpoint must not send a ``from`` filter.
        config = SPARKPOST_ENDPOINTS["suppression_list"]
        params = _build_initial_params(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert "from" not in params


class TestBuildInitialUrl:
    def test_events_url_with_params(self) -> None:
        config = SPARKPOST_ENDPOINTS["events"]
        url = _build_initial_url("https://api.sparkpost.com", config, {"cursor": "initial", "per_page": 1000})
        parsed = urlparse(url)
        assert parsed.path == "/api/v1/events/message"
        query = parse_qs(parsed.query)
        assert query["cursor"] == ["initial"]
        assert query["per_page"] == ["1000"]

    def test_no_params(self) -> None:
        config = SPARKPOST_ENDPOINTS["templates"]
        assert (
            _build_initial_url("https://api.sparkpost.com", config, {}) == "https://api.sparkpost.com/api/v1/templates"
        )


class TestComputeNextUrl:
    HOST = "https://api.sparkpost.com"

    def test_cursor_follows_relative_next_href(self) -> None:
        config = SPARKPOST_ENDPOINTS["events"]
        nxt = _compute_next_url(
            config,
            {"links": [{"href": "/api/v1/events/message?cursor=abc&per_page=1000", "rel": "next"}]},
            self.HOST,
        )
        assert nxt == "https://api.sparkpost.com/api/v1/events/message?cursor=abc&per_page=1000"

    def test_cursor_follows_absolute_next_href(self) -> None:
        config = SPARKPOST_ENDPOINTS["events"]
        nxt = _compute_next_url(
            config,
            {"links": [{"href": "https://api.sparkpost.com/api/v1/events/message?cursor=abc", "rel": "next"}]},
            self.HOST,
        )
        assert nxt == "https://api.sparkpost.com/api/v1/events/message?cursor=abc"

    def test_cursor_no_next_rel_terminates(self) -> None:
        config = SPARKPOST_ENDPOINTS["events"]
        assert (
            _compute_next_url(
                config, {"links": [{"href": "/api/v1/events/message?cursor=x", "rel": "previous"}]}, self.HOST
            )
            is None
        )

    def test_cursor_no_links_terminates(self) -> None:
        config = SPARKPOST_ENDPOINTS["events"]
        assert _compute_next_url(config, {"total_count": 0}, self.HOST) is None

    def test_non_cursor_endpoint_never_paginates(self) -> None:
        config = SPARKPOST_ENDPOINTS["templates"]
        assert (
            _compute_next_url(config, {"links": [{"href": "/api/v1/templates?page=2", "rel": "next"}]}, self.HOST)
            is None
        )

    @pytest.mark.parametrize(
        "next_href",
        [
            "https://evil.example.com/steal",  # off-host
            "http://api.sparkpost.com/api/v1/events/message",  # non-https
            "https://api.sparkpost.com.evil.com/api/v1/events/message",  # look-alike host
        ],
    )
    def test_cursor_rejects_offhost_next(self, next_href: str) -> None:
        config = SPARKPOST_ENDPOINTS["events"]
        assert _compute_next_url(config, {"links": [{"href": next_href, "rel": "next"}]}, self.HOST) is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            (401, False),
            # 403 = genuine key without the Account scope used by the probe; don't block connecting.
            (403, True),
            (500, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.sparkpost.make_tracked_session"
    )
    def test_status_mapping(self, mock_session: mock.MagicMock, status_code: int, expected_valid: bool) -> None:
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        is_valid, error = validate_credentials("us", "key")

        assert is_valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.sparkpost.make_tracked_session"
    )
    def test_request_exception_is_caught(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
        is_valid, error = validate_credentials("us", "key")
        assert is_valid is False
        assert error is not None


class TestSparkPostSourceResponse:
    @pytest.mark.parametrize(
        ("endpoint", "expected_pk", "expect_partition"),
        [
            ("events", ["event_id"], True),
            ("suppression_list", ["recipient", "type"], True),
            ("recipient_lists", ["id"], False),
            ("sending_domains", ["domain"], False),
        ],
    )
    def test_source_response_shape(self, endpoint: str, expected_pk: list[str], expect_partition: bool) -> None:
        manager = mock.MagicMock()
        response = sparkpost_source(
            region="us",
            api_key="key",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=manager,
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        assert response.sort_mode == "asc"
        if expect_partition:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [SPARKPOST_ENDPOINTS[endpoint].partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestGetRowsResume:
    def _run(
        self, endpoint: str, pages: list[Any], can_resume: bool, resume_url: str | None
    ) -> tuple[list[Any], list[str], list[str]]:
        manager = mock.MagicMock()
        manager.can_resume.return_value = can_resume
        manager.load_state.return_value = SparkPostResumeConfig(next_url=resume_url) if resume_url else None
        saved: list[str] = []
        manager.save_state.side_effect = lambda state: saved.append(state.next_url)

        fetched_urls: list[str] = []

        def fake_get(url: str, timeout: Any = None) -> Any:
            fetched_urls.append(url)
            resp = mock.MagicMock()
            resp.status_code = 200
            resp.ok = True
            resp.json.return_value = pages[len(fetched_urls) - 1]
            return resp

        with mock.patch.object(sp, "make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = fake_get
            rows = list(
                sp.get_rows(
                    region="us",
                    api_key="key",
                    endpoint=endpoint,
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                )
            )
        return rows, saved, fetched_urls

    def test_cursor_pagination_yields_and_saves_state(self) -> None:
        pages = [
            {
                "results": [{"event_id": "1", "timestamp": "2026-01-01T00:00:00.000Z"}],
                "links": [{"href": "/api/v1/events/message?cursor=p2", "rel": "next"}],
            },
            {"results": [{"event_id": "2", "timestamp": "2026-01-01T00:01:00.000Z"}], "links": []},
        ]
        rows, saved, fetched = self._run("events", pages, can_resume=False, resume_url=None)

        assert rows[0][0]["event_id"] == "1"
        assert rows[1][0]["event_id"] == "2"
        # State saved after the first batch (before fetching page 2), pointing at the next page.
        assert saved == ["https://api.sparkpost.com/api/v1/events/message?cursor=p2"]
        assert fetched[1] == "https://api.sparkpost.com/api/v1/events/message?cursor=p2"

    def test_empty_results_terminates_without_saving(self) -> None:
        pages = [{"results": [], "links": [{"href": "/api/v1/events/message?cursor=p2", "rel": "next"}]}]
        rows, saved, fetched = self._run("events", pages, can_resume=False, resume_url=None)
        assert rows == []
        assert saved == []
        assert len(fetched) == 1

    def test_non_paginated_endpoint_fetches_once(self) -> None:
        pages = [{"results": [{"id": "t1"}, {"id": "t2"}]}]
        rows, saved, fetched = self._run("templates", pages, can_resume=False, resume_url=None)
        assert rows == [[{"id": "t1"}, {"id": "t2"}]]
        assert saved == []
        assert len(fetched) == 1

    def test_resumes_from_saved_url(self) -> None:
        pages = [{"results": [{"event_id": "9"}], "links": []}]
        _rows, _saved, fetched = self._run(
            "events", pages, can_resume=True, resume_url="https://api.sparkpost.com/resume-here"
        )
        assert fetched[0] == "https://api.sparkpost.com/resume-here"

    @pytest.mark.parametrize(
        "resume_url",
        [
            "https://evil.example.com/steal",
            "http://api.sparkpost.com/resume-here",
            "https://api.sparkpost.com.evil.com/resume-here",
        ],
    )
    def test_tampered_resume_url_is_rejected(self, resume_url: str) -> None:
        pages = [{"results": [{"event_id": "9"}], "links": []}]
        with pytest.raises(ValueError, match="unexpected URL"):
            self._run("events", pages, can_resume=True, resume_url=resume_url)
