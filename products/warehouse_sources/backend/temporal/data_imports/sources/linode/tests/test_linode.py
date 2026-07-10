import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.linode import linode
from products.warehouse_sources.backend.temporal.data_imports.sources.linode.linode import (
    PAGE_SIZE,
    LinodeResumeConfig,
    LinodeRetryableError,
    _build_x_filter,
    _format_filter_value,
    _page_url,
    get_rows,
    linode_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linode.settings import LINODE_ENDPOINTS


class TestFormatFilterValue:
    @parameterized.expand(
        [
            ("integer_passthrough", 12345, 12345),
            ("string_passthrough", "abc", "abc"),
            ("aware_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00"),
        ]
    )
    def test_format_filter_value(self, _name: str, value: Any, expected: Any) -> None:
        # A "+00:00" offset in the filter value would make Linode reject the X-Filter, so datetimes
        # must render without one.
        assert _format_filter_value(value) == expected


class TestBuildXFilter:
    def test_first_sync_has_no_gte_bound(self) -> None:
        # A missing watermark must produce an order-only filter, never `{"+gte": None}`, which the API
        # would reject and wedge every first sync.
        assert _build_x_filter("id", None) == {"+order_by": "id", "+order": "asc"}

    def test_watermark_adds_ascending_gte_bound(self) -> None:
        # Ordering must always be ascending so rows arrive oldest-first, matching sort_mode="asc";
        # otherwise the watermark would checkpoint to ~now after the first batch.
        assert _build_x_filter("date", datetime(2026, 3, 4, 2, 58, 14)) == {
            "+order_by": "date",
            "+order": "asc",
            "date": {"+gte": "2026-03-04T02:58:14"},
        }


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, True),
            ("invalid_token", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_valid: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        response.text = "body"
        with patch.object(linode, "make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = response
            valid, _message = validate_credentials("tok")
        assert valid is expected_valid

    def test_network_error_is_not_valid(self) -> None:
        with patch.object(linode, "make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
            valid, message = validate_credentials("tok")
        assert valid is False
        assert message is not None


class TestFetchPageRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status_code: int) -> None:
        response = MagicMock()
        response.status_code = status_code
        response.headers = {"Retry-After": "1"}
        session = MagicMock()
        session.get.return_value = response

        with patch.object(linode._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(LinodeRetryableError):
                linode._fetch_page(session, "https://api.linode.com/v4/volumes", {}, MagicMock())

        # 5 attempts before giving up (reraise=True).
        assert session.get.call_count == 5

    def test_transient_error_retried_then_succeeds(self) -> None:
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"data": [], "pages": 1}
        session = MagicMock()
        session.get.side_effect = [requests.ReadTimeout("slow"), good]

        with patch.object(linode._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = linode._fetch_page(session, "https://api.linode.com/v4/volumes", {}, MagicMock())

        assert result == {"data": [], "pages": 1}
        assert session.get.call_count == 2


class _FakeResumableManager:
    def __init__(self, state: LinodeResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[LinodeResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> LinodeResumeConfig | None:
        return self._state

    def save_state(self, data: LinodeResumeConfig) -> None:
        self.saved.append(data)


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager, pages_by_url: dict[str, Any], endpoint: str = "volumes", **incremental: Any
    ) -> tuple[list[dict], list[dict[str, str]]]:
        captured_headers: list[dict[str, str]] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            captured_headers.append(dict(headers))
            return pages_by_url[url]

        rows: list[dict] = []
        with patch.object(linode, "_fetch_page", fake_fetch):
            for table in get_rows(
                api_token="tok",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
                **incremental,
            ):
                rows.extend(table.to_pylist())
        return rows, captured_headers

    def test_paginates_across_all_pages(self) -> None:
        pages = {
            _page_url("/volumes", 1): {"data": [{"id": 1}, {"id": 2}], "page": 1, "pages": 2},
            _page_url("/volumes", 2): {"data": [{"id": 3}], "page": 2, "pages": 2},
        }
        rows, _headers = self._collect(_FakeResumableManager(), pages)
        assert [r["id"] for r in rows] == [1, 2, 3]

    def test_resumes_from_saved_page(self) -> None:
        # Fixtures omit page 1, so resuming anywhere other than page 2 fails loudly with a KeyError.
        pages = {_page_url("/volumes", 2): {"data": [{"id": 3}], "page": 2, "pages": 2}}
        rows, _headers = self._collect(_FakeResumableManager(LinodeResumeConfig(next_page=2)), pages)
        assert [r["id"] for r in rows] == [3]

    def test_full_refresh_sends_no_x_filter(self) -> None:
        pages = {_page_url("/volumes", 1): {"data": [{"id": 1}], "page": 1, "pages": 1}}
        _rows, headers = self._collect(
            _FakeResumableManager(),
            pages,
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert all("X-Filter" not in h for h in headers)

    def test_incremental_endpoint_attaches_x_filter_with_watermark(self) -> None:
        # A regression that stops threading the watermark into the X-Filter would silently revert
        # incremental events to a full refresh; assert the id `+gte` bound is present on the request.
        pages = {_page_url("/account/events", 1): {"data": [{"id": 5}], "page": 1, "pages": 1}}
        _rows, headers = self._collect(
            _FakeResumableManager(),
            pages,
            endpoint="events",
            should_use_incremental_field=True,
            db_incremental_field_last_value=4,
            incremental_field="id",
        )
        assert json.loads(headers[0]["X-Filter"]) == {"+order_by": "id", "+order": "asc", "id": {"+gte": 4}}

    def test_page_size_is_maxed(self) -> None:
        assert f"page_size={PAGE_SIZE}" in _page_url("/volumes", 1)
        assert PAGE_SIZE == 500

    def test_saves_next_page_after_yielding_a_chunk(self) -> None:
        # Force a mid-sync yield (chunk_size is 2000) so we exercise the resume checkpoint: after the
        # first chunk flushes it must persist the NEXT page, not the current one, so an append-only
        # resume never re-yields already-committed rows.
        pages = {
            _page_url("/volumes", 1): {"data": [{"id": i} for i in range(2001)], "page": 1, "pages": 2},
            _page_url("/volumes", 2): {"data": [{"id": 9001}], "page": 2, "pages": 2},
        }
        manager = _FakeResumableManager()
        rows, _headers = self._collect(manager, pages)
        assert len(rows) == 2002
        assert manager.saved == [LinodeResumeConfig(next_page=2)]


class TestLinodeSource:
    def test_sort_mode_is_ascending(self) -> None:
        response = linode_source(
            api_token="tok", endpoint="events", logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.sort_mode == "asc"

    @parameterized.expand(
        [
            ("invoices", "date", True),
            ("events", "created", True),
            ("domains", None, False),
            ("users", None, False),
        ]
    )
    def test_partitioning_matches_stable_field(
        self, endpoint: str, partition_key: str | None, partitioned: bool
    ) -> None:
        response = linode_source(
            api_token="tok", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        if partitioned:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None

    def test_primary_keys_come_from_endpoint_config(self) -> None:
        response = linode_source(
            api_token="tok", endpoint="users", logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.primary_keys == ["username"]
        assert LINODE_ENDPOINTS["events"].primary_keys == ["id"]
