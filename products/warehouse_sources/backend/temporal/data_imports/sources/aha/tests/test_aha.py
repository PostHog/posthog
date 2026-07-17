from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.aha import aha
from products.warehouse_sources.backend.temporal.data_imports.sources.aha.aha import (
    PER_PAGE,
    AhaResumeConfig,
    _build_initial_params,
    _build_url,
    _format_updated_since,
    _has_more_pages,
    get_rows,
    normalize_subdomain,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aha.settings import AHA_ENDPOINTS


class TestNormalizeSubdomain:
    @parameterized.expand(
        [
            ("bare", "acme", "acme"),
            ("full_host", "acme.aha.io", "acme"),
            ("https_url", "https://acme.aha.io", "acme"),
            ("trailing_slash", "acme.aha.io/", "acme"),
            ("with_hyphen", "acme-corp", "acme-corp"),
            ("whitespace", "  acme  ", "acme"),
        ]
    )
    def test_valid_subdomains(self, _name: str, value: str, expected: str) -> None:
        assert normalize_subdomain(value) == expected

    @parameterized.expand(
        [
            ("path_injection", "acme/../evil"),
            ("host_injection", "acme.evil.com"),
            ("userinfo_injection", "acme@evil.com"),
            ("empty", ""),
            ("space_inside", "ac me"),
            ("trailing_hyphen", "acme-"),
        ]
    )
    def test_invalid_subdomains_raise(self, _name: str, value: str) -> None:
        with pytest.raises(ValueError):
            normalize_subdomain(value)


class TestFormatUpdatedSince:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        result = _format_updated_since(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildInitialParams:
    def test_incremental_endpoint_with_cursor_adds_updated_since(self) -> None:
        params = _build_initial_params(
            AHA_ENDPOINTS["features"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert params == {"per_page": PER_PAGE, "updated_since": "2026-03-04T02:58:14Z"}

    def test_incremental_endpoint_without_cursor_omits_updated_since(self) -> None:
        params = _build_initial_params(
            AHA_ENDPOINTS["features"], should_use_incremental_field=True, db_incremental_field_last_value=None
        )
        assert params == {"per_page": PER_PAGE}

    def test_full_refresh_endpoint_never_filters(self) -> None:
        # goals has no server-side `updated_since`; a cursor must not leak into the request.
        params = _build_initial_params(
            AHA_ENDPOINTS["goals"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params == {"per_page": PER_PAGE}


class TestBuildUrl:
    def test_no_params(self) -> None:
        assert _build_url("https://acme.aha.io/api/v1", "/me", {}) == "https://acme.aha.io/api/v1/me"

    def test_encodes_params(self) -> None:
        url = _build_url(
            "https://acme.aha.io/api/v1", "/features", {"page": 2, "updated_since": "2026-03-04T02:58:14Z"}
        )
        assert url == "https://acme.aha.io/api/v1/features?page=2&updated_since=2026-03-04T02%3A58%3A14Z"


class TestHasMorePages:
    @parameterized.expand(
        [
            ("more_pages", {"current_page": 1, "total_pages": 3}, 1, 200, True),
            ("last_page", {"current_page": 3, "total_pages": 3}, 3, 50, False),
            ("missing_meta_full_page", {}, 1, PER_PAGE, True),
            ("missing_meta_partial_page", {}, 1, 5, False),
        ]
    )
    def test_has_more(self, _name: str, pagination: dict, page: int, item_count: int, expected: bool) -> None:
        assert _has_more_pages(pagination, page, item_count) is expected


class _FakeResumableManager:
    def __init__(self, state: AhaResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[AhaResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> AhaResumeConfig | None:
        return self._state

    def save_state(self, data: AhaResumeConfig) -> None:
        self.saved.append(data)


class _FakeBatcher:
    """Yields one batch per item so save-after-yield behavior is observable without 2000+ rows."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._rows: list[dict] = []

    def batch(self, row: dict) -> None:
        self._rows.append(row)

    def should_yield(self, include_incomplete_chunk: bool = False) -> bool:
        return len(self._rows) > 0

    def get_table(self) -> list[dict]:
        rows = self._rows
        self._rows = []
        return rows


def _patch_fetch(monkeypatch: Any, pages: dict[str, Any]) -> list[str]:
    fetched: list[str] = []

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        fetched.append(url)
        return pages[url]

    monkeypatch.setattr(aha, "_fetch_page", fake_fetch)
    return fetched


def _collect(monkeypatch: Any, manager: _FakeResumableManager, **kwargs: Any) -> list[dict]:
    monkeypatch.setattr(aha, "Batcher", _FakeBatcher)
    rows: list[dict] = []
    for batch in get_rows(
        subdomain="acme",
        api_key="key",
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(batch)
    return rows


class TestGetRows:
    def test_paginates_until_last_page(self, monkeypatch: Any) -> None:
        pages = {
            "https://acme.aha.io/api/v1/features?per_page=200&page=1": {
                "features": [{"id": "1"}, {"id": "2"}],
                "pagination": {"current_page": 1, "total_pages": 2},
            },
            "https://acme.aha.io/api/v1/features?per_page=200&page=2": {
                "features": [{"id": "3"}],
                "pagination": {"current_page": 2, "total_pages": 2},
            },
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="features")

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        assert fetched == list(pages)

    def test_saves_resume_state_after_each_yielded_page(self, monkeypatch: Any) -> None:
        pages = {
            "https://acme.aha.io/api/v1/features?per_page=200&page=1": {
                "features": [{"id": "1"}],
                "pagination": {"current_page": 1, "total_pages": 2},
            },
            "https://acme.aha.io/api/v1/features?per_page=200&page=2": {
                "features": [{"id": "2"}],
                "pagination": {"current_page": 2, "total_pages": 2},
            },
        }
        _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()
        _collect(monkeypatch, manager, endpoint="features")

        # State is saved only while more pages remain (page 1 -> next_page 2), never on the last page.
        assert manager.saved == [AhaResumeConfig(next_page=2)]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        pages = {
            "https://acme.aha.io/api/v1/features?per_page=200&page=2": {
                "features": [{"id": "2"}],
                "pagination": {"current_page": 2, "total_pages": 2},
            },
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(AhaResumeConfig(next_page=2)), endpoint="features")

        assert [r["id"] for r in rows] == ["2"]
        assert fetched == ["https://acme.aha.io/api/v1/features?per_page=200&page=2"]

    def test_incremental_cursor_added_to_request(self, monkeypatch: Any) -> None:
        pages = {
            "https://acme.aha.io/api/v1/features?per_page=200&updated_since=2026-03-04T02%3A58%3A14Z&page=1": {
                "features": [{"id": "1"}],
                "pagination": {"current_page": 1, "total_pages": 1},
            },
        }
        fetched = _patch_fetch(monkeypatch, pages)
        _collect(
            monkeypatch,
            _FakeResumableManager(),
            endpoint="features",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert "updated_since=2026-03-04T02%3A58%3A14Z" in fetched[0]

    def test_uses_response_key_for_todos(self, monkeypatch: Any) -> None:
        # to-dos live at /tasks with a `tasks` root key.
        pages = {
            "https://acme.aha.io/api/v1/tasks?per_page=200&page=1": {
                "tasks": [{"id": "t1"}],
                "pagination": {"current_page": 1, "total_pages": 1},
            },
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="todos")

        assert [r["id"] for r in rows] == ["t1"]
        assert fetched == ["https://acme.aha.io/api/v1/tasks?per_page=200&page=1"]

    def test_stops_on_empty_page(self, monkeypatch: Any) -> None:
        pages = {
            "https://acme.aha.io/api/v1/goals?per_page=200&page=1": {
                "goals": [],
                "pagination": {"current_page": 1, "total_pages": 1},
            },
        }
        _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="goals")

        assert rows == []
