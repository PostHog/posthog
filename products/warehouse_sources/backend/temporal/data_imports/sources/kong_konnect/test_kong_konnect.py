from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.kong_konnect import kong_konnect
from products.warehouse_sources.backend.temporal.data_imports.sources.kong_konnect.kong_konnect import (
    MAX_PAGE_SIZE,
    KongKonnectResumeConfig,
    _build_body,
    _clamp_future_value_to_now,
    _format_datetime,
    _resolve_window,
    get_rows,
    kong_konnect_source,
    validate_credentials,
)


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format_datetime(self, _name: str, value: object, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestBuildBody:
    def test_body_is_absolute_ascending_window(self) -> None:
        body = _build_body("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", offset=200, size=1000)
        assert body["time_range"] == {
            "type": "absolute",
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-02T00:00:00Z",
            "tz": "Etc/UTC",
        }
        # Ascending order is load-bearing: the pipeline advances the watermark trusting asc order.
        assert body["order"] == "ascending"
        assert body["size"] == 1000
        assert body["offset"] == 200
        assert body["filters"] == []


class TestResolveWindow:
    @freeze_time("2026-06-15T12:00:00Z")
    def test_incremental_starts_at_watermark(self) -> None:
        start, end = _resolve_window(
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 10, 8, 0, 0, tzinfo=UTC),
            lookback_days=30,
        )
        assert start == "2026-06-10T08:00:00Z"
        assert end == "2026-06-15T12:00:00Z"

    @freeze_time("2026-06-15T12:00:00Z")
    def test_full_refresh_walks_back_lookback_days(self) -> None:
        start, end = _resolve_window(
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            lookback_days=7,
        )
        assert start == "2026-06-08T12:00:00Z"
        assert end == "2026-06-15T12:00:00Z"

    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_watermark_clamped_to_now(self) -> None:
        # A future-dated cursor would otherwise produce start > end, wedging every later sync.
        start, _ = _resolve_window(
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2027, 1, 1, tzinfo=UTC),
            lookback_days=30,
        )
        assert start == "2026-06-15T12:00:00Z"


class TestClampFutureValue:
    @parameterized.expand(
        [
            ("past_datetime_untouched", datetime(2026, 1, 1, tzinfo=UTC), False),
            ("future_datetime_clamped", datetime(2027, 1, 1, tzinfo=UTC), True),
        ]
    )
    @freeze_time("2026-06-15T12:00:00Z")
    def test_clamp(self, _name: str, value: datetime, should_clamp: bool) -> None:
        result = _clamp_future_value_to_now(value)
        if should_clamp:
            assert result == datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
        else:
            assert result == value


def _manager(resume: KongKonnectResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _page(count: int) -> dict[str, Any]:
    return {"results": [{"request_id": f"r{i}"} for i in range(count)], "meta": {}}


class TestGetRowsPagination:
    @patch.object(kong_konnect, "make_tracked_session")
    @patch.object(kong_konnect, "_fetch_page")
    def test_stops_on_short_page_and_advances_offset(self, mock_fetch: MagicMock, _mock_session: MagicMock) -> None:
        # Two full pages then a short page terminates pagination.
        mock_fetch.side_effect = [_page(MAX_PAGE_SIZE), _page(MAX_PAGE_SIZE), _page(3)]
        manager = _manager()

        batches = list(get_rows("tok", "us", "api_requests", MagicMock(), manager, lookback_days=30))

        assert [len(b) for b in batches] == [MAX_PAGE_SIZE, MAX_PAGE_SIZE, 3]
        assert mock_fetch.call_count == 3
        # Offsets requested must walk forward by page size.
        offsets = [call.args[3]["offset"] for call in mock_fetch.call_args_list]
        assert offsets == [0, MAX_PAGE_SIZE, 2 * MAX_PAGE_SIZE]

    @patch.object(kong_konnect, "make_tracked_session")
    @patch.object(kong_konnect, "_fetch_page")
    def test_empty_first_page_yields_nothing(self, mock_fetch: MagicMock, _mock_session: MagicMock) -> None:
        mock_fetch.side_effect = [_page(0)]
        batches = list(get_rows("tok", "us", "api_requests", MagicMock(), _manager(), lookback_days=30))
        assert batches == []

    @patch.object(kong_konnect, "make_tracked_session")
    @patch.object(kong_konnect, "_fetch_page")
    def test_saves_state_after_full_page_only(self, mock_fetch: MagicMock, _mock_session: MagicMock) -> None:
        mock_fetch.side_effect = [_page(MAX_PAGE_SIZE), _page(2)]
        manager = _manager()

        list(get_rows("tok", "us", "api_requests", MagicMock(), manager, lookback_days=30))

        # One save after the first (full) page; the final short page must NOT persist state.
        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args.args[0]
        assert saved.offset == MAX_PAGE_SIZE

    @freeze_time("2026-06-15T12:00:00Z")
    @patch.object(kong_konnect, "make_tracked_session")
    @patch.object(kong_konnect, "_fetch_page")
    def test_resume_reuses_saved_window_not_recomputed(self, mock_fetch: MagicMock, _mock_session: MagicMock) -> None:
        # A crash saved a mid-window checkpoint; resume must re-issue that exact window + offset,
        # never recompute `end` as "now" (which would shift the window and skip/duplicate rows).
        mock_fetch.side_effect = [_page(1)]
        resume = KongKonnectResumeConfig(start="2026-01-01T00:00:00Z", end="2026-01-05T00:00:00Z", offset=5000)

        list(get_rows("tok", "us", "api_requests", MagicMock(), _manager(resume), lookback_days=30))

        body = mock_fetch.call_args_list[0].args[3]
        assert body["time_range"]["start"] == "2026-01-01T00:00:00Z"
        assert body["time_range"]["end"] == "2026-01-05T00:00:00Z"
        assert body["offset"] == 5000


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @patch.object(kong_konnect, "make_tracked_session")
    def test_status_mapping(self, _name: str, status: int, expected: bool, mock_session: MagicMock) -> None:
        response = MagicMock()
        response.status_code = status
        mock_session.return_value.post.return_value = response
        assert validate_credentials("tok", "us") is expected

    @patch.object(kong_konnect, "make_tracked_session")
    def test_network_error_is_false(self, mock_session: MagicMock) -> None:
        mock_session.return_value.post.side_effect = requests.ConnectionError()
        assert validate_credentials("tok", "us") is False


class TestKongKonnectSourceResponse:
    def test_source_response_shape(self) -> None:
        response = kong_konnect_source("tok", "eu", "api_requests", MagicMock(), _manager())
        assert response.name == "api_requests"
        assert response.primary_keys == ["request_id"]
        # asc must match the ascending request order for the watermark to advance correctly.
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["request_start"]


if __name__ == "__main__":
    pytest.main([__file__])
