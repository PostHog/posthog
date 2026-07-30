from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.roark import roark
from products.warehouse_sources.backend.temporal.data_imports.sources.roark.roark import (
    RoarkResumeConfig,
    _base_params,
    _build_url,
    _iter_pages,
    get_rows,
    roark_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.roark.settings import ENDPOINTS, ROARK_ENDPOINTS


def _logger() -> MagicMock:
    return MagicMock()


class TestBuildUrl:
    def test_no_params(self) -> None:
        assert _build_url("/call", {}) == "https://api.roark.ai/v1/call"

    def test_with_params_is_encoded(self) -> None:
        url = _build_url("/call", {"limit": 100, "after": "abc def"})
        assert url == "https://api.roark.ai/v1/call?limit=100&after=abc+def"


class TestBaseParams:
    def test_cursor_endpoint_with_sort(self) -> None:
        # call supports sortBy/sortDirection and caps at 100
        params = _base_params(ROARK_ENDPOINTS["call"])
        assert params == {"limit": 100, "sortBy": "createdAt", "sortDirection": "asc"}

    def test_cursor_endpoint_without_sort(self) -> None:
        params = _base_params(ROARK_ENDPOINTS["agent"])
        assert params == {"limit": 50}
        assert "sortBy" not in params

    def test_unpaginated_endpoint_sends_no_limit(self) -> None:
        # metric_definition takes no pagination params at all
        params = _base_params(ROARK_ENDPOINTS["metric_definition"])
        assert params == {}


class TestIterPagesCursor:
    def test_walks_cursor_until_has_more_false(self) -> None:
        pages = [
            {"data": [{"id": "1"}], "pagination": {"hasMore": True, "nextCursor": "c1"}},
            {"data": [{"id": "2"}], "pagination": {"hasMore": True, "nextCursor": "c2"}},
            {"data": [{"id": "3"}], "pagination": {"hasMore": False, "nextCursor": None}},
        ]
        with patch.object(roark, "_fetch_page", side_effect=pages):
            result = list(_iter_pages(MagicMock(), {}, ROARK_ENDPOINTS["agent"], _logger(), resume=None))

        assert [p.items for p in result] == [[{"id": "1"}], [{"id": "2"}], [{"id": "3"}]]
        # Each page records the cursor that fetched IT, so a resume re-fetches the same page.
        assert [p.resume_state.after for p in result] == [None, "c1", "c2"]

    def test_stops_when_next_cursor_missing_even_if_has_more(self) -> None:
        pages = [{"data": [{"id": "1"}], "pagination": {"hasMore": True, "nextCursor": None}}]
        with patch.object(roark, "_fetch_page", side_effect=pages):
            result = list(_iter_pages(MagicMock(), {}, ROARK_ENDPOINTS["agent"], _logger(), resume=None))
        assert len(result) == 1

    def test_resume_starts_from_saved_cursor(self) -> None:
        pages = [{"data": [{"id": "9"}], "pagination": {"hasMore": False, "nextCursor": None}}]
        captured_urls: list[str] = []

        def fake_fetch(session: Any, url: str, headers: Any, logger: Any) -> dict:
            captured_urls.append(url)
            return pages.pop(0)

        with patch.object(roark, "_fetch_page", side_effect=fake_fetch):
            list(
                _iter_pages(
                    MagicMock(),
                    {},
                    ROARK_ENDPOINTS["agent"],
                    _logger(),
                    resume=RoarkResumeConfig(after="saved-cursor"),
                )
            )

        assert "after=saved-cursor" in captured_urls[0]


class TestIterPagesOffset:
    def test_walks_offset_advancing_by_rows_returned(self) -> None:
        # A non-final page returning fewer rows than max_page_size must advance the offset by the
        # rows actually returned, or rows in the gap would be skipped on the next request.
        pages = [
            {"data": [{"id": "1"}, {"id": "2"}, {"id": "3"}], "pagination": {"hasMore": True}},
            {"data": [{"id": "4"}], "pagination": {"hasMore": False}},
        ]
        captured_urls: list[str] = []

        def fake_fetch(session: Any, url: str, headers: Any, logger: Any) -> dict:
            captured_urls.append(url)
            return pages.pop(0)

        with patch.object(roark, "_fetch_page", side_effect=fake_fetch):
            result = list(_iter_pages(MagicMock(), {}, ROARK_ENDPOINTS["issue"], _logger(), resume=None))

        assert [p.resume_state.offset for p in result] == [0, 3]
        assert "offset=0" in captured_urls[0]
        assert "offset=3" in captured_urls[1]

    def test_resume_starts_from_saved_offset(self) -> None:
        pages = [{"data": [], "pagination": {"limit": 100, "offset": 200, "hasMore": False}}]
        captured_urls: list[str] = []

        def fake_fetch(session: Any, url: str, headers: Any, logger: Any) -> dict:
            captured_urls.append(url)
            return pages.pop(0)

        with patch.object(roark, "_fetch_page", side_effect=fake_fetch):
            list(
                _iter_pages(
                    MagicMock(),
                    {},
                    ROARK_ENDPOINTS["issue"],
                    _logger(),
                    resume=RoarkResumeConfig(offset=200),
                )
            )

        assert "offset=200" in captured_urls[0]


class TestIterPagesNone:
    def test_single_unpaginated_fetch(self) -> None:
        with patch.object(roark, "_fetch_page", return_value={"data": [{"id": "1"}, {"id": "2"}]}) as fetch:
            result = list(_iter_pages(MagicMock(), {}, ROARK_ENDPOINTS["metric_definition"], _logger(), resume=None))
        assert fetch.call_count == 1
        assert result[0].items == [{"id": "1"}, {"id": "2"}]

    def test_handles_bare_top_level_list_response(self) -> None:
        # Unpaginated endpoints may return a bare list instead of a `{"data": [...]}` envelope; those
        # rows must still be synced rather than silently dropped.
        with patch.object(roark, "_fetch_page", return_value=[{"id": "1"}, {"id": "2"}]):
            result = list(_iter_pages(MagicMock(), {}, ROARK_ENDPOINTS["metric_definition"], _logger(), resume=None))
        assert [item["id"] for page in result for item in page.items] == ["1", "2"]


class _FakeBatcher:
    """Yields a table after every batched row so save-after-yield is observable in tests."""

    def __init__(self, **kwargs: Any) -> None:
        self._rows: list[dict] = []

    def batch(self, row: dict) -> None:
        self._rows.append(row)

    def should_yield(self, include_incomplete_chunk: bool = False) -> bool:
        return bool(self._rows)

    def get_table(self) -> list[dict]:
        rows = self._rows
        self._rows = []
        return rows


class TestGetRows:
    def test_saves_current_page_cursor_after_yield(self) -> None:
        pages = [
            {"data": [{"id": "1"}], "pagination": {"hasMore": True, "nextCursor": "c1"}},
            {"data": [{"id": "2"}], "pagination": {"hasMore": False, "nextCursor": None}},
        ]
        manager = MagicMock()
        manager.can_resume.return_value = False

        with (
            patch.object(roark, "_fetch_page", side_effect=pages),
            patch.object(roark, "make_tracked_session", return_value=MagicMock()),
            patch.object(roark, "Batcher", _FakeBatcher),
        ):
            tables = list(get_rows("key", "agent", _logger(), manager))

        assert tables == [[{"id": "1"}], [{"id": "2"}]]
        # The saved cursor is the one that fetched the page being processed (None for page 1, "c1" for
        # page 2) — so a resume re-fetches that page rather than skipping its un-yielded tail.
        saved = [call.args[0].after for call in manager.save_state.call_args_list]
        assert saved == [None, "c1"]

    def test_resume_loads_saved_state(self) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = RoarkResumeConfig(after="resume-cursor")
        captured_urls: list[str] = []

        def fake_fetch(session: Any, url: str, headers: Any, logger: Any) -> dict:
            captured_urls.append(url)
            return {"data": [], "pagination": {"hasMore": False, "nextCursor": None}}

        with (
            patch.object(roark, "_fetch_page", side_effect=fake_fetch),
            patch.object(roark, "make_tracked_session", return_value=MagicMock()),
            patch.object(roark, "Batcher", _FakeBatcher),
        ):
            list(get_rows("key", "agent", _logger(), manager))

        assert "after=resume-cursor" in captured_urls[0]


class TestValidateCredentials:
    @parameterized.expand([(200, True), (401, False), (403, False), (500, False)])
    def test_status_maps_to_validity(self, status: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status)
        with patch.object(roark, "make_tracked_session", return_value=session):
            assert validate_credentials("key") is expected

    def test_network_error_is_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with patch.object(roark, "make_tracked_session", return_value=session):
            assert validate_credentials("key") is False


class TestRoarkSourceResponse:
    def test_response_uses_endpoint_primary_keys_and_partition(self) -> None:
        response = roark_source("key", "call", _logger(), MagicMock())
        assert response.name == "call"
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["startedAt"]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"

    def test_plan_job_uses_non_id_primary_key(self) -> None:
        response = roark_source("key", "simulation_plan_job", _logger(), MagicMock())
        assert response.primary_keys == ["simulationRunPlanJobId"]

    def test_issue_reports_desc_sort_mode(self) -> None:
        # The issue endpoint is fixed newest-first, so we must not claim ascending order.
        response = roark_source("key", "issue", _logger(), MagicMock())
        assert response.sort_mode == "desc"

    def test_metric_definition_has_no_partition(self) -> None:
        response = roark_source("key", "metric_definition", _logger(), MagicMock())
        assert response.partition_mode is None
        assert response.partition_keys is None

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_every_endpoint_builds_a_response(self, endpoint: str) -> None:
        response = roark_source("key", endpoint, _logger(), MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == ROARK_ENDPOINTS[endpoint].primary_keys


class TestFetchPageRetry:
    @parameterized.expand([(429,), (500,), (503,)])
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status, ok=False, text="err")
        # Bypass tenacity's retry wrapping to assert the raised error type directly.
        with pytest.raises(roark.RoarkRetryableError):
            roark._fetch_page.__wrapped__(session, "https://api.roark.ai/v1/agent", {}, _logger())  # type: ignore[attr-defined]
