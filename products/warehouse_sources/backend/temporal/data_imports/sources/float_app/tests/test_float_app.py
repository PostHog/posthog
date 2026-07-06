from typing import Any

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.float_app import float_app
from products.warehouse_sources.backend.temporal.data_imports.sources.float_app.float_app import (
    DELETE_LOG_LIMIT,
    PER_PAGE,
    FloatAppResumeConfig,
    _build_url,
    _extract_items,
    _header_int,
    get_rows,
    validate_credentials,
)


class TestExtractItems:
    @parameterized.expand(
        [
            ("bare_list", [{"people_id": 1}], [{"people_id": 1}]),
            ("wrapped_data", {"data": [{"a": 1}]}, [{"a": 1}]),
            ("wrapped_items", {"items": [{"b": 2}]}, [{"b": 2}]),
            ("unexpected_dict", {"x": 1}, []),
            ("empty_list", [], []),
        ]
    )
    def test_extract_items(self, _name: str, payload: Any, expected: list) -> None:
        assert _extract_items(payload) == expected


class TestHeaderInt:
    @parameterized.expand(
        [
            ("valid", {"X-Pagination-Pages": "5"}, 5),
            ("missing", {}, None),
            ("non_numeric", {"X-Pagination-Pages": "abc"}, None),
        ]
    )
    def test_header_int(self, _name: str, headers: dict, expected: int | None) -> None:
        assert _header_int(headers, "X-Pagination-Pages") == expected


class TestBuildUrl:
    def test_no_params(self) -> None:
        assert _build_url("/people", {}) == "https://api.float.com/v3/people"

    def test_encodes_params(self) -> None:
        assert (
            _build_url("/people", {"per-page": 200, "page": 2}) == "https://api.float.com/v3/people?per-page=200&page=2"
        )


class _FakeResponse:
    def __init__(self, items: Any, headers: dict[str, str]) -> None:
        self._items = items
        self.headers = headers
        self.status_code = 200
        self.ok = True

    def json(self) -> Any:
        return self._items


class _FakeResumableManager:
    def __init__(self, state: FloatAppResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[FloatAppResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> FloatAppResumeConfig | None:
        return self._state

    def save_state(self, data: FloatAppResumeConfig) -> None:
        self.saved.append(data)


class _FakeBatcher:
    """Accumulates rows and only yields once a full chunk is buffered, like the real Batcher.

    ``chunk_size`` defaults to 1 (yield per item) so most tests observe save-after-yield behavior
    without thousands of rows. A larger ``chunk_size`` lets a chunk fill partway through a page, which
    exercises the mid-page-save scenario: the yield/save happens after the page is fully batched, so the
    resume pointer must still advance exactly once per page boundary — never mid-page.
    """

    def __init__(self, *args: Any, chunk_size: int = 1, **kwargs: Any) -> None:
        self._rows: list[dict] = []
        self._chunk_size = chunk_size

    def batch(self, row: dict) -> None:
        self._rows.append(row)

    def should_yield(self, include_incomplete_chunk: bool = False) -> bool:
        if include_incomplete_chunk:
            return len(self._rows) > 0
        return len(self._rows) >= self._chunk_size

    def get_table(self) -> list[dict]:
        rows = self._rows
        self._rows = []
        return rows


def _patch_fetch(monkeypatch: Any, pages: dict[str, _FakeResponse]) -> list[str]:
    fetched: list[str] = []

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> _FakeResponse:
        fetched.append(url)
        return pages[url]

    monkeypatch.setattr(float_app, "_fetch_page", fake_fetch)
    return fetched


def _collect(monkeypatch: Any, manager: _FakeResumableManager, endpoint: str, chunk_size: int = 1) -> list[dict]:
    # Ignore the real chunk_size get_rows passes; drive it from the test so a chunk can span a page.
    monkeypatch.setattr(float_app, "Batcher", lambda *a, **k: _FakeBatcher(chunk_size=chunk_size))
    rows: list[dict] = []
    for batch in get_rows(api_key="tok", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=manager):  # type: ignore[arg-type]
        rows.extend(batch)
    return rows


class TestGetRowsPagePagination:
    def test_paginates_until_last_page_via_header(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.float.com/v3/people?per-page=200&page=1": _FakeResponse(
                [{"people_id": "1"}, {"people_id": "2"}], {"X-Pagination-Pages": "2"}
            ),
            "https://api.float.com/v3/people?per-page=200&page=2": _FakeResponse(
                [{"people_id": "3"}], {"X-Pagination-Pages": "2"}
            ),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), "people")

        assert [r["people_id"] for r in rows] == ["1", "2", "3"]
        assert fetched == list(pages)

    def test_falls_back_to_full_page_heuristic_when_header_absent(self, monkeypatch: Any) -> None:
        # No X-Pagination-Pages header: a full page (== PER_PAGE) implies another page may follow;
        # a short page ends the walk. Without this fallback a header-less response truncates at page 1.
        pages = {
            "https://api.float.com/v3/roles?per-page=200&page=1": _FakeResponse(
                [{"id": str(i)} for i in range(PER_PAGE)], {}
            ),
            "https://api.float.com/v3/roles?per-page=200&page=2": _FakeResponse([{"id": "last"}], {}),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), "roles")

        assert len(rows) == PER_PAGE + 1
        assert fetched == list(pages)

    def test_saves_resume_state_after_each_page_except_last(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.float.com/v3/people?per-page=200&page=1": _FakeResponse(
                [{"people_id": "1"}], {"X-Pagination-Pages": "2"}
            ),
            "https://api.float.com/v3/people?per-page=200&page=2": _FakeResponse(
                [{"people_id": "2"}], {"X-Pagination-Pages": "2"}
            ),
        }
        _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()
        _collect(monkeypatch, manager, "people")

        assert manager.saved == [FloatAppResumeConfig(next_page=2)]

    def test_saves_state_once_per_page_when_chunk_spans_page(self, monkeypatch: Any) -> None:
        # The resume pointer must advance exactly once per page boundary. Page 1 has four items against
        # chunk_size=2, so the buffer crosses a chunk boundary twice within the page. If the save were
        # mid-page (inside the item loop) it would fire on each crossing, writing next_page=2 twice;
        # done once after the page is fully batched, it writes next_page=2 exactly once.
        pages = {
            "https://api.float.com/v3/people?per-page=200&page=1": _FakeResponse(
                [{"people_id": str(i)} for i in range(4)], {"X-Pagination-Pages": "2"}
            ),
            "https://api.float.com/v3/people?per-page=200&page=2": _FakeResponse(
                [{"people_id": "4"}], {"X-Pagination-Pages": "2"}
            ),
        }
        _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()
        _collect(monkeypatch, manager, "people", chunk_size=2)

        assert manager.saved == [FloatAppResumeConfig(next_page=2)]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.float.com/v3/people?per-page=200&page=2": _FakeResponse(
                [{"people_id": "2"}], {"X-Pagination-Pages": "2"}
            ),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(FloatAppResumeConfig(next_page=2)), "people")

        assert [r["people_id"] for r in rows] == ["2"]
        assert fetched == ["https://api.float.com/v3/people?per-page=200&page=2"]

    def test_stops_on_empty_page(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.float.com/v3/projects?per-page=200&page=1": _FakeResponse([], {"X-Pagination-Pages": "1"}),
        }
        _patch_fetch(monkeypatch, pages)
        assert _collect(monkeypatch, _FakeResumableManager(), "projects") == []


class TestGetRowsCursorPagination:
    def test_advances_via_cursor_and_stops_on_short_page(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.float.com/v3/deleted/tasks?limit=500": _FakeResponse(
                [{"task_id": i} for i in range(DELETE_LOG_LIMIT)],
                {"X-Pagination-Next-Cursor": "c2", "X-Pagination-Has-More": "true"},
            ),
            "https://api.float.com/v3/deleted/tasks?limit=500&cursor=c2": _FakeResponse(
                [{"task_id": 999}], {"X-Pagination-Next-Cursor": "", "X-Pagination-Has-More": "false"}
            ),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), "deleted_tasks")

        assert len(rows) == DELETE_LOG_LIMIT + 1
        assert fetched == list(pages)

    def test_terminates_when_full_page_has_no_advancing_cursor(self, monkeypatch: Any) -> None:
        # A full page whose cursor header is missing (or unchanged) must NOT loop forever — the
        # defensive guard stops after one page rather than re-requesting the same cursor endlessly.
        pages = {
            "https://api.float.com/v3/deleted/tasks?limit=500": _FakeResponse(
                [{"task_id": i} for i in range(DELETE_LOG_LIMIT)], {}
            ),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), "deleted_tasks")

        assert len(rows) == DELETE_LOG_LIMIT
        assert fetched == list(pages)

    def test_saves_next_cursor_after_yield(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.float.com/v3/deleted/tasks?limit=500": _FakeResponse(
                [{"task_id": i} for i in range(DELETE_LOG_LIMIT)],
                {"X-Pagination-Next-Cursor": "c2", "X-Pagination-Has-More": "true"},
            ),
            "https://api.float.com/v3/deleted/tasks?limit=500&cursor=c2": _FakeResponse([{"task_id": 999}], {}),
        }
        _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()
        _collect(monkeypatch, manager, "deleted_tasks")

        assert FloatAppResumeConfig(next_cursor="c2") in manager.saved

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.float.com/v3/deleted/tasks?limit=500&cursor=c2": _FakeResponse([{"task_id": 999}], {}),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(FloatAppResumeConfig(next_cursor="c2")), "deleted_tasks")

        assert [r["task_id"] for r in rows] == [999]
        assert fetched == ["https://api.float.com/v3/deleted/tasks?limit=500&cursor=c2"]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, (True, 200)),
            (401, (False, 401)),
            (403, (False, 403)),
        ],
    )
    def test_maps_status_code(self, status_code: int, expected: tuple, monkeypatch: Any) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response
        monkeypatch.setattr(float_app, "make_tracked_session", lambda *a, **k: session)

        assert validate_credentials("tok") == expected

    def test_transport_error_returns_none_status(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("connection reset")
        monkeypatch.setattr(float_app, "make_tracked_session", lambda *a, **k: session)

        assert validate_credentials("tok") == (False, None)
