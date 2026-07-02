from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.northpass_lms import northpass_lms
from products.warehouse_sources.backend.temporal.data_imports.sources.northpass_lms.northpass_lms import (
    NorthpassResumeConfig,
    _build_url,
    _flatten_item,
    get_rows,
    northpass_source,
)


class TestBuildUrl:
    def test_no_params(self):
        assert _build_url("/courses", {}) == "https://api.northpass.com/v2/courses"

    def test_encodes_params(self):
        assert _build_url("/courses", {"limit": 100}) == "https://api.northpass.com/v2/courses?limit=100"


class TestFlattenItem:
    def test_promotes_attributes_and_drops_links(self):
        item = {
            "id": "c1",
            "type": "courses",
            "attributes": {"name": "Intro", "created_at": "2024-10-08T08:37:18Z"},
            "links": {"self": "https://api.northpass.com/v2/courses/c1"},
            "relationships": {"categories": {"data": []}},
        }
        row = _flatten_item(item)

        assert row["id"] == "c1"
        assert row["type"] == "courses"
        assert row["name"] == "Intro"
        assert row["created_at"] == "2024-10-08T08:37:18Z"
        assert "links" not in row
        assert "attributes" not in row
        assert row["relationships"] == {"categories": {"data": []}}

    def test_injects_extra_parent_id(self):
        item = {"id": "e1", "type": "course_enrollments", "attributes": {"progress": 30}}
        row = _flatten_item(item, extra={"course_id": "c1"})

        assert row["course_id"] == "c1"
        assert row["progress"] == 30

    def test_tolerates_missing_attributes(self):
        row = _flatten_item({"id": "x", "type": "quizzes"})
        assert row == {"id": "x", "type": "quizzes"}


class _FakeResumableManager:
    def __init__(self, state: NorthpassResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[NorthpassResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> NorthpassResumeConfig | None:
        return self._state

    def save_state(self, data: NorthpassResumeConfig) -> None:
        self.saved.append(data)


def _patch_fetch(monkeypatch: Any, pages: dict[str, Any]) -> list[str]:
    fetched: list[str] = []

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        fetched.append(url)
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(northpass_lms, "_fetch_page", fake_fetch)
    monkeypatch.setattr(northpass_lms, "make_tracked_session", lambda *a, **k: MagicMock())
    return fetched


def _collect(manager: _FakeResumableManager, endpoint: str) -> list[dict]:
    rows: list[dict] = []
    for batch in get_rows(api_key="key", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=manager):
        rows.extend(batch)
    return rows


class TestTopLevelPagination:
    def test_paginates_until_next_link_missing(self, monkeypatch: Any):
        pages = {
            "https://api.northpass.com/v2/courses?limit=100": {
                "data": [{"id": "1", "attributes": {"name": "a"}}, {"id": "2", "attributes": {"name": "b"}}],
                "links": {"next": "https://api.northpass.com/v2/courses?page=2&limit=100"},
            },
            "https://api.northpass.com/v2/courses?page=2&limit=100": {
                "data": [{"id": "3", "attributes": {"name": "c"}}],
                "links": {},
            },
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(_FakeResumableManager(), "courses")

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        assert [r["name"] for r in rows] == ["a", "b", "c"]
        assert fetched == list(pages)

    def test_saves_resume_state_only_while_pages_remain(self, monkeypatch: Any):
        pages = {
            "https://api.northpass.com/v2/courses?limit=100": {
                "data": [{"id": "1"}],
                "links": {"next": "https://api.northpass.com/v2/courses?page=2&limit=100"},
            },
            "https://api.northpass.com/v2/courses?page=2&limit=100": {"data": [{"id": "2"}], "links": {}},
        }
        _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()
        _collect(manager, "courses")

        # Saved after yielding page 1 (more remains), never after the last page.
        assert manager.saved == [
            NorthpassResumeConfig(next_url="https://api.northpass.com/v2/courses?page=2&limit=100")
        ]

    def test_resumes_from_saved_next_url(self, monkeypatch: Any):
        pages = {
            "https://api.northpass.com/v2/courses?page=2&limit=100": {"data": [{"id": "2"}], "links": {}},
        }
        fetched = _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager(
            NorthpassResumeConfig(next_url="https://api.northpass.com/v2/courses?page=2&limit=100")
        )
        rows = _collect(manager, "courses")

        assert [r["id"] for r in rows] == ["2"]
        # The first page is skipped entirely — resume starts at the saved URL.
        assert fetched == ["https://api.northpass.com/v2/courses?page=2&limit=100"]


class TestFanOut:
    def _parent_and_children(self) -> dict[str, Any]:
        return {
            # Parent enumeration (two courses).
            "https://api.northpass.com/v2/courses?limit=100": {
                "data": [{"id": "c1"}, {"id": "c2"}],
                "links": {},
            },
            "https://api.northpass.com/v2/courses/c1/enrollments?limit=100": {
                "data": [{"id": "e1", "attributes": {"progress": 30}}],
                "links": {},
            },
            "https://api.northpass.com/v2/courses/c2/enrollments?limit=100": {
                "data": [{"id": "e2", "attributes": {"progress": 60}}],
                "links": {},
            },
        }

    def test_injects_parent_id_into_every_child_row(self, monkeypatch: Any):
        _patch_fetch(monkeypatch, self._parent_and_children())
        rows = _collect(_FakeResumableManager(), "course_enrollments")

        by_id = {r["id"]: r for r in rows}
        assert by_id["e1"]["course_id"] == "c1"
        assert by_id["e2"]["course_id"] == "c2"
        # The injected parent id is what keeps the [course_id, id] primary key unique table-wide.
        assert by_id["e1"]["progress"] == 30

    def test_advances_parent_bookmark_between_parents(self, monkeypatch: Any):
        _patch_fetch(monkeypatch, self._parent_and_children())
        manager = _FakeResumableManager()
        _collect(manager, "course_enrollments")

        # After finishing c1, the bookmark advances to c2 so a crash resumes at the next parent.
        assert NorthpassResumeConfig(next_url=None, parent_id="c2") in manager.saved

    def test_resumes_from_parent_bookmark_skipping_earlier_parents(self, monkeypatch: Any):
        pages = self._parent_and_children()
        fetched = _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager(NorthpassResumeConfig(next_url=None, parent_id="c2"))
        rows = _collect(manager, "course_enrollments")

        assert [r["id"] for r in rows] == ["e2"]
        # c1's enrollments must not be re-fetched when resuming into c2.
        assert "https://api.northpass.com/v2/courses/c1/enrollments?limit=100" not in fetched

    def test_skips_parent_that_404s_mid_fanout(self, monkeypatch: Any):
        pages = self._parent_and_children()
        error = requests.HTTPError()
        error.response = MagicMock(status_code=404)
        pages["https://api.northpass.com/v2/courses/c1/enrollments?limit=100"] = error
        _patch_fetch(monkeypatch, pages)

        rows = _collect(_FakeResumableManager(), "course_enrollments")

        # c1 vanished mid-sync; its 404 is swallowed and c2 still syncs.
        assert [r["id"] for r in rows] == ["e2"]

    def test_reraises_non_404_child_error(self, monkeypatch: Any):
        pages = self._parent_and_children()
        error = requests.HTTPError()
        error.response = MagicMock(status_code=500)
        pages["https://api.northpass.com/v2/courses/c1/enrollments?limit=100"] = error
        _patch_fetch(monkeypatch, pages)

        with pytest.raises(requests.HTTPError):
            _collect(_FakeResumableManager(), "course_enrollments")


class TestNorthpassSource:
    @parameterized.expand(
        [
            ("people", ["id"], "created_at"),
            ("courses", ["id"], "created_at"),
            ("course_enrollments", ["course_id", "id"], "enrolled_at"),
            ("learning_path_enrollments", ["learning_path_id", "id"], "enrolled_at"),
        ]
    )
    def test_source_response_carries_endpoint_keys_and_partitioning(self, endpoint, primary_keys, partition_key):
        response = northpass_source(
            api_key="key", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
