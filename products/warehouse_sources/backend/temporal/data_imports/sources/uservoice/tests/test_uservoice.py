from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.uservoice import uservoice
from products.warehouse_sources.backend.temporal.data_imports.sources.uservoice.settings import PER_PAGE
from products.warehouse_sources.backend.temporal.data_imports.sources.uservoice.uservoice import (
    UservoiceResumeConfig,
    _build_initial_params,
    _build_url,
    _format_updated_after,
    _next_page,
    get_rows,
    normalize_subdomain,
    uservoice_source,
)


class TestNormalizeSubdomain:
    @parameterized.expand(
        [
            ("bare", "acme", "acme"),
            ("full_host", "acme.uservoice.com", "acme"),
            ("https_url", "https://acme.uservoice.com", "acme"),
            ("trailing_slash", "acme.uservoice.com/", "acme"),
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


class TestFormatUpdatedAfter:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        result = _format_updated_after(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildInitialParams:
    def test_incremental_endpoint_with_value_adds_updated_after(self) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.uservoice.settings import (
            USERVOICE_ENDPOINTS,
        )

        params = _build_initial_params(
            USERVOICE_ENDPOINTS["suggestions"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert params == {"per_page": PER_PAGE, "updated_after": "2026-03-04T02:58:14Z"}

    def test_incremental_endpoint_without_value_omits_updated_after(self) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.uservoice.settings import (
            USERVOICE_ENDPOINTS,
        )

        params = _build_initial_params(
            USERVOICE_ENDPOINTS["suggestions"], should_use_incremental_field=True, db_incremental_field_last_value=None
        )
        assert params == {"per_page": PER_PAGE}

    def test_full_refresh_endpoint_never_filters(self) -> None:
        # labels has no server-side `updated_after`; a cursor value must not leak into the request.
        from products.warehouse_sources.backend.temporal.data_imports.sources.uservoice.settings import (
            USERVOICE_ENDPOINTS,
        )

        params = _build_initial_params(
            USERVOICE_ENDPOINTS["labels"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params == {"per_page": PER_PAGE}


class TestBuildUrl:
    def test_no_params(self) -> None:
        base = "https://acme.uservoice.com/api/v2/admin"
        assert _build_url(base, "/suggestions", {}) == f"{base}/suggestions"

    def test_encodes_params(self) -> None:
        base = "https://acme.uservoice.com/api/v2/admin"
        url = _build_url(base, "/suggestions", {"page": 2, "updated_after": "2026-03-04T02:58:14Z"})
        assert url == f"{base}/suggestions?page=2&updated_after=2026-03-04T02%3A58%3A14Z"


class TestNextPage:
    def test_cursor_takes_priority(self) -> None:
        # A present cursor is followed even when page metadata would say "last page".
        result = _next_page({"cursor": "abc", "page": 3, "total_pages": 3}, current_page=3, item_count=100)
        assert result is not None
        assert result.cursor == "abc"
        assert result.page is None

    @parameterized.expand(
        [
            ("more_pages", {"page": 1, "total_pages": 3}, 1, 100, 2),
            ("current_page_alias", {"current_page": 1, "total_pages": 2}, 1, 100, 2),
        ]
    )
    def test_page_fallback_advances(
        self, _name: str, pagination: dict, current_page: int, item_count: int, expected_page: int
    ) -> None:
        result = _next_page(pagination, current_page, item_count)
        assert result is not None
        assert result.cursor is None
        assert result.page == expected_page

    @parameterized.expand(
        [
            ("last_page", {"page": 3, "total_pages": 3}, 3, 50),
            ("missing_meta_partial_page", {}, 1, 5),
        ]
    )
    def test_terminates(self, _name: str, pagination: dict, current_page: int, item_count: int) -> None:
        assert _next_page(pagination, current_page, item_count) is None

    def test_missing_meta_full_page_keeps_going(self) -> None:
        result = _next_page({}, current_page=1, item_count=PER_PAGE)
        assert result is not None
        assert result.page == 2


class _FakeResumableManager:
    def __init__(self, state: UservoiceResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[UservoiceResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> UservoiceResumeConfig | None:
        return self._state

    def save_state(self, data: UservoiceResumeConfig) -> None:
        self.saved.append(data)


def _patch_fetch(monkeypatch: Any, pages: dict[str, Any]) -> list[str]:
    fetched: list[str] = []

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        fetched.append(url)
        return pages[url]

    monkeypatch.setattr(uservoice, "_fetch_page", fake_fetch)
    monkeypatch.setattr(uservoice, "make_tracked_session", lambda *a, **k: MagicMock())
    return fetched


def _collect(monkeypatch: Any, manager: _FakeResumableManager, **kwargs: Any) -> list[dict]:
    rows: list[dict] = []
    for batch in get_rows(
        subdomain="acme",
        api_key="token",
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(batch)
    return rows


class TestGetRows:
    _BASE = "https://acme.uservoice.com/api/v2/admin"

    def test_paginates_by_page_number(self, monkeypatch: Any) -> None:
        pages = {
            f"{self._BASE}/suggestions?per_page={PER_PAGE}": {
                "suggestions": [{"id": 1}, {"id": 2}],
                "pagination": {"page": 1, "total_pages": 2},
            },
            f"{self._BASE}/suggestions?per_page={PER_PAGE}&page=2": {
                "suggestions": [{"id": 3}],
                "pagination": {"page": 2, "total_pages": 2},
            },
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="suggestions")

        assert [r["id"] for r in rows] == [1, 2, 3]
        assert fetched == list(pages)

    def test_paginates_by_cursor(self, monkeypatch: Any) -> None:
        pages = {
            f"{self._BASE}/suggestions?per_page={PER_PAGE}": {
                "suggestions": [{"id": 1}],
                "pagination": {"cursor": "CUR2"},
            },
            f"{self._BASE}/suggestions?per_page={PER_PAGE}&cursor=CUR2": {
                "suggestions": [{"id": 2}],
                "pagination": {},
            },
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="suggestions")

        assert [r["id"] for r in rows] == [1, 2]
        assert fetched == list(pages)

    def test_stops_on_non_advancing_cursor(self, monkeypatch: Any) -> None:
        # A cursor that repeats itself must not loop forever.
        pages = {
            f"{self._BASE}/suggestions?per_page={PER_PAGE}": {
                "suggestions": [{"id": 1}],
                "pagination": {"cursor": "SAME"},
            },
            f"{self._BASE}/suggestions?per_page={PER_PAGE}&cursor=SAME": {
                "suggestions": [{"id": 2}],
                "pagination": {"cursor": "SAME"},
            },
        }
        _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="suggestions")

        assert [r["id"] for r in rows] == [1, 2]

    def test_saves_resume_state_after_each_page_only_while_more_remain(self, monkeypatch: Any) -> None:
        pages = {
            f"{self._BASE}/suggestions?per_page={PER_PAGE}": {
                "suggestions": [{"id": 1}],
                "pagination": {"page": 1, "total_pages": 2},
            },
            f"{self._BASE}/suggestions?per_page={PER_PAGE}&page=2": {
                "suggestions": [{"id": 2}],
                "pagination": {"page": 2, "total_pages": 2},
            },
        }
        _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()
        _collect(monkeypatch, manager, endpoint="suggestions")

        assert manager.saved == [UservoiceResumeConfig(cursor=None, page=2)]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        pages = {
            f"{self._BASE}/suggestions?per_page={PER_PAGE}&page=2": {
                "suggestions": [{"id": 2}],
                "pagination": {"page": 2, "total_pages": 2},
            },
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(UservoiceResumeConfig(page=2)), endpoint="suggestions")

        assert [r["id"] for r in rows] == [2]
        assert fetched == [f"{self._BASE}/suggestions?per_page={PER_PAGE}&page=2"]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        pages = {
            f"{self._BASE}/suggestions?per_page={PER_PAGE}&cursor=CUR9": {
                "suggestions": [{"id": 9}],
                "pagination": {},
            },
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(
            monkeypatch, _FakeResumableManager(UservoiceResumeConfig(cursor="CUR9")), endpoint="suggestions"
        )

        assert [r["id"] for r in rows] == [9]
        assert fetched == [f"{self._BASE}/suggestions?per_page={PER_PAGE}&cursor=CUR9"]

    def test_incremental_filter_added_to_request(self, monkeypatch: Any) -> None:
        url = f"{self._BASE}/suggestions?per_page={PER_PAGE}&updated_after=2026-03-04T02%3A58%3A14Z"
        pages = {url: {"suggestions": [{"id": 1}], "pagination": {"page": 1, "total_pages": 1}}}
        fetched = _patch_fetch(monkeypatch, pages)
        _collect(
            monkeypatch,
            _FakeResumableManager(),
            endpoint="suggestions",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert "updated_after=2026-03-04T02%3A58%3A14Z" in fetched[0]

    def test_stops_on_empty_response(self, monkeypatch: Any) -> None:
        pages = {
            f"{self._BASE}/labels?per_page={PER_PAGE}": {"labels": [], "pagination": {"page": 1, "total_pages": 1}},
        }
        _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="labels")

        assert rows == []


class TestUservoiceSourceResponse:
    @parameterized.expand(
        [
            # Incremental endpoints defer the watermark write to job end via "desc" (order is unverified).
            ("suggestions", "desc", "created_at"),
            ("tickets", "desc", "created_at"),
            # Full-refresh endpoints don't checkpoint a watermark, so they stay on the default "asc".
            ("labels", "asc", "created_at"),
        ]
    )
    def test_sort_mode_and_partitioning(self, endpoint: str, expected_sort: str, partition_key: str) -> None:
        response = uservoice_source(
            subdomain="acme",
            api_key="token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == expected_sort
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]
