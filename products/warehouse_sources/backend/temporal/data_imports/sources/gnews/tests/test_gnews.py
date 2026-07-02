from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.gnews import gnews
from products.warehouse_sources.backend.temporal.data_imports.sources.gnews.gnews import (
    MAX_PAGES,
    GNewsResumeConfig,
    _build_params,
    _flatten_article,
    _format_from_value,
    get_rows,
    gnews_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gnews.settings import GNEWS_ENDPOINTS, PAGE_SIZE

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.gnews.gnews"


class TestFormatFromValue:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime_treated_as_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("non_date_returns_none", "not-a-date", None),
            ("none_returns_none", None, None),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str | None) -> None:
        with freeze_time("2026-06-01T00:00:00Z"):
            assert _format_from_value(value) == expected

    def test_future_value_capped_to_now(self) -> None:
        # A future cursor would filter out every article; capping keeps the request a valid no-op.
        with freeze_time("2026-06-01T12:00:00Z"):
            assert _format_from_value(datetime(2099, 1, 1, tzinfo=UTC)) == "2026-06-01T12:00:00Z"


class TestBuildParams:
    def test_search_sends_query_not_category(self) -> None:
        params = _build_params(GNEWS_ENDPOINTS["articles"], "posthog", "technology", None, None, None, 1)
        assert params["q"] == "posthog"
        assert "category" not in params
        assert params["sortby"] == "publishedAt"
        assert params["max"] == PAGE_SIZE

    def test_search_query_truncated_to_200_chars(self) -> None:
        params = _build_params(GNEWS_ENDPOINTS["articles"], "x" * 250, None, None, None, None, 1)
        assert len(params["q"]) == 200

    def test_top_headlines_sends_category_not_query(self) -> None:
        params = _build_params(GNEWS_ENDPOINTS["top_headlines"], "posthog", "business", None, None, None, 2)
        assert params["category"] == "business"
        assert "q" not in params
        assert params["page"] == 2

    def test_optional_filters_and_from_included_when_present(self) -> None:
        params = _build_params(GNEWS_ENDPOINTS["articles"], "posthog", None, "en", "us", "2026-01-01T00:00:00Z", 1)
        assert params["lang"] == "en"
        assert params["country"] == "us"
        assert params["from"] == "2026-01-01T00:00:00Z"

    def test_omitted_optional_filters(self) -> None:
        params = _build_params(GNEWS_ENDPOINTS["articles"], "posthog", None, None, None, None, 1)
        assert "lang" not in params
        assert "country" not in params
        assert "from" not in params


class TestFlattenArticle:
    def test_source_object_lifted_onto_row(self) -> None:
        row = _flatten_article(
            {
                "title": "t",
                "url": "https://example.com/a",
                "source": {"id": "s1", "name": "Example", "url": "https://example.com", "country": "us"},
            }
        )
        assert "source" not in row
        assert row["source_id"] == "s1"
        assert row["source_name"] == "Example"
        assert row["source_url"] == "https://example.com"
        assert row["source_country"] == "us"
        # The primary key column is untouched.
        assert row["url"] == "https://example.com/a"

    def test_missing_source_is_tolerated(self) -> None:
        row = _flatten_article({"title": "t", "url": "https://example.com/a"})
        assert row == {"title": "t", "url": "https://example.com/a"}


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, {}, True),
            ("bad_key_401", 401, {}, False),
            ("missing_key_400", 400, {}, False),
            ("quota_403", 403, {}, False),
            ("other_error_with_body", 422, {"errors": ["Something went wrong"]}, False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, body: dict, expected_valid: bool) -> None:
        response = MagicMock(status_code=status)
        response.json.return_value = body
        session = MagicMock()
        session.get.return_value = response
        with patch(f"{_MODULE}.make_tracked_session", return_value=session):
            valid, message = validate_credentials("some-key")
        assert valid is expected_valid
        if not expected_valid:
            assert message

    def test_request_exception_returns_error(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.exceptions.ConnectionError("boom")
        with patch(f"{_MODULE}.make_tracked_session", return_value=session):
            valid, message = validate_credentials("some-key")
        assert valid is False
        assert "boom" in (message or "")


def _resume_manager(state: GNewsResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = state is not None
    manager.load_state.return_value = state
    return manager


def _page(num_articles: int, start: int = 0) -> dict:
    return {
        "totalArticles": 9999,
        "articles": [
            {"title": f"a{start + i}", "url": f"https://example.com/{start + i}", "publishedAt": "2026-01-01T00:00:00Z"}
            for i in range(num_articles)
        ],
    }


def _collect(rows_iter) -> list[dict]:
    out: list[dict] = []
    for table in rows_iter:
        out.extend(table.to_pylist() if hasattr(table, "to_pylist") else table)
    return out


class TestGetRows:
    def test_stops_on_short_page(self) -> None:
        # A page shorter than PAGE_SIZE is the last page — pagination must stop there.
        pages = [_page(PAGE_SIZE, start=0), _page(3, start=PAGE_SIZE)]
        with patch(f"{_MODULE}._fetch_page", side_effect=pages) as fetch:
            rows = _collect(get_rows("k", "articles", "posthog", None, None, None, MagicMock(), _resume_manager()))
        assert fetch.call_count == 2
        assert len(rows) == PAGE_SIZE + 3
        # source object flattening happened on the way out.
        assert "source" not in rows[0]

    def test_stops_at_max_pages_cap(self) -> None:
        # Every page is full, so only the 1000-article ceiling (MAX_PAGES) halts pagination.
        with patch(f"{_MODULE}._fetch_page", side_effect=lambda *a, **k: _page(PAGE_SIZE)) as fetch:
            _collect(get_rows("k", "articles", "posthog", None, None, None, MagicMock(), _resume_manager()))
        assert fetch.call_count == MAX_PAGES

    def test_resumes_from_saved_page(self) -> None:
        with patch(f"{_MODULE}._fetch_page", return_value=_page(2)):
            with patch(f"{_MODULE}._build_params", wraps=gnews._build_params) as build:
                _collect(
                    get_rows(
                        "k",
                        "articles",
                        "posthog",
                        None,
                        None,
                        None,
                        MagicMock(),
                        _resume_manager(GNewsResumeConfig(page_to_refetch=5)),
                    )
                )
        # First (and only, since page 2 rows < PAGE_SIZE) request starts at the saved page.
        assert build.call_args_list[0].args[-1] == 5

    def test_incremental_passes_from_filter(self) -> None:
        with patch(f"{_MODULE}._fetch_page", return_value=_page(1)):
            with patch(f"{_MODULE}._build_params", wraps=gnews._build_params) as build:
                _collect(
                    get_rows(
                        "k",
                        "articles",
                        "posthog",
                        None,
                        None,
                        None,
                        MagicMock(),
                        _resume_manager(),
                        should_use_incremental_field=True,
                        db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                        incremental_field="publishedAt",
                    )
                )
        # from_value threaded into the params.
        assert build.call_args_list[0].args[5] == "2026-01-01T00:00:00Z"

    def test_pagination_403_beyond_first_page_stops_gracefully(self) -> None:
        forbidden = requests.HTTPError(response=MagicMock(status_code=403))
        # Page 1 is full (forces a page 2 request); page 2 is a plan-restricted 403.
        with patch(f"{_MODULE}._fetch_page", side_effect=[_page(PAGE_SIZE), forbidden]):
            rows = _collect(get_rows("k", "articles", "posthog", None, None, None, MagicMock(), _resume_manager()))
        # We keep page 1's rows rather than failing the whole sync.
        assert len(rows) == PAGE_SIZE

    def test_403_on_first_page_raises(self) -> None:
        forbidden = requests.HTTPError(response=MagicMock(status_code=403))
        with patch(f"{_MODULE}._fetch_page", side_effect=forbidden):
            with pytest.raises(requests.HTTPError):
                _collect(get_rows("k", "articles", "posthog", None, None, None, MagicMock(), _resume_manager()))


class _FakeBatcher:
    """Yields after every batched row so the save-state-after-yield contract is observable."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._pending: list[dict] = []

    def batch(self, row: dict) -> None:
        self._pending.append(row)

    def should_yield(self, include_incomplete_chunk: bool = False) -> bool:
        return bool(self._pending)

    def get_table(self) -> list[dict]:
        out, self._pending = self._pending, []
        return out


class TestResumableStateSaving:
    def test_state_saved_with_current_page_after_yield(self) -> None:
        manager = _resume_manager()
        # Two full pages then a short page, so page 1 and 2 each checkpoint before advancing.
        pages = [_page(PAGE_SIZE, 0), _page(PAGE_SIZE, PAGE_SIZE), _page(1, 2 * PAGE_SIZE)]
        with patch(f"{_MODULE}.Batcher", _FakeBatcher):
            with patch(f"{_MODULE}._fetch_page", side_effect=pages):
                _collect(get_rows("k", "articles", "posthog", None, None, None, MagicMock(), manager))
        saved_pages = [call.args[0].page_to_refetch for call in manager.save_state.call_args_list]
        # Checkpoints record the page that produced the batch (current page), never a page ahead.
        assert 1 in saved_pages
        assert 2 in saved_pages
        assert max(saved_pages) <= 2


class TestGnewsSource:
    @parameterized.expand([("articles",), ("top_headlines",)])
    def test_source_response_contract(self, endpoint: str) -> None:
        response = gnews_source("k", endpoint, "posthog", "general", None, None, MagicMock(), _resume_manager())
        assert response.name == endpoint
        assert response.primary_keys == ["url"]
        # GNews only offers newest-first ordering; asc would corrupt the incremental watermark.
        assert response.sort_mode == "desc"
        assert response.partition_keys == ["publishedAt"]
        assert response.partition_mode == "datetime"
