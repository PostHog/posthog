from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.news_api import news_api
from products.warehouse_sources.backend.temporal.data_imports.sources.news_api.news_api import (
    PAGE_SIZE,
    NewsApiResumeConfig,
    _build_params,
    _error_code,
    _format_from_value,
    get_rows,
    news_api_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.news_api.settings import NEWS_API_ENDPOINTS


class TestFormatFromValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            ("naive_datetime_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            ("date_value", date(2026, 3, 4), "2026-03-04"),
            ("string_passthrough", "2026-03-04T00:00:00", "2026-03-04T00:00:00"),
            ("empty_string", "", None),
            ("none", None, None),
        ]
    )
    def test_format_from_value(self, _name: str, value: Any, expected: str | None) -> None:
        assert _format_from_value(value) == expected


class TestBuildParams:
    def test_everything_incremental_includes_from_and_sort(self) -> None:
        params = _build_params(
            NEWS_API_ENDPOINTS["everything"],
            query="bitcoin",
            language="en",
            page=1,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert params["q"] == "bitcoin"
        assert params["sortBy"] == "publishedAt"
        assert params["pageSize"] == PAGE_SIZE
        assert params["page"] == 1
        assert params["language"] == "en"
        assert params["from"] == "2026-03-04T02:58:14"

    def test_everything_without_incremental_omits_from(self) -> None:
        # A full refresh (or first sync) must not send a `from` filter, or it would clip history.
        params = _build_params(
            NEWS_API_ENDPOINTS["everything"],
            query="bitcoin",
            language=None,
            page=2,
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert "from" not in params
        assert "language" not in params
        assert params["page"] == 2

    def test_top_headlines_has_no_date_filter_or_language(self) -> None:
        # top-headlines exposes no `from`/`to` and no `language` param, so neither should leak in even
        # when a cursor value / language is supplied.
        params = _build_params(
            NEWS_API_ENDPOINTS["top_headlines"],
            query="bitcoin",
            language="en",
            page=1,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params["q"] == "bitcoin"
        assert params["pageSize"] == PAGE_SIZE
        assert "from" not in params
        assert "sortBy" not in params
        assert "language" not in params

    def test_sources_ignores_query_and_pagination(self) -> None:
        # /v2/top-headlines/sources takes neither q nor pagination; only optional facet filters.
        params = _build_params(
            NEWS_API_ENDPOINTS["sources"],
            query="bitcoin",
            language="en",
            page=1,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert params == {"language": "en"}


class TestErrorCode:
    def test_extracts_code_from_body(self) -> None:
        resp = MagicMock()
        resp.json.return_value = {"status": "error", "code": "maximumResultsReached"}
        assert _error_code(requests.HTTPError(response=resp)) == "maximumResultsReached"

    def test_returns_none_when_body_not_json(self) -> None:
        resp = MagicMock()
        resp.json.side_effect = ValueError("no json")
        assert _error_code(requests.HTTPError(response=resp)) is None

    def test_returns_none_without_response(self) -> None:
        assert _error_code(requests.HTTPError()) is None


class TestFetchPageRetry:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_codes_retry(self, _name: str, status_code: int) -> None:
        retryable = MagicMock(status_code=status_code)
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"articles": []}

        session = MagicMock()
        session.get.side_effect = [retryable, good]

        with patch.object(news_api._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = news_api._fetch_page(session, "https://newsapi.org/v2/everything", {}, MagicMock())

        assert result == {"articles": []}
        assert session.get.call_count == 2

    def test_client_error_raises_immediately(self) -> None:
        # A 401 is a permanent credential failure — it must surface at once, not burn retries.
        resp = MagicMock(status_code=401, ok=False, text="unauthorized")
        resp.raise_for_status.side_effect = requests.HTTPError("401 Client Error")
        session = MagicMock()
        session.get.return_value = resp

        with pytest.raises(requests.HTTPError):
            news_api._fetch_page(session, "https://newsapi.org/v2/everything", {}, MagicMock())

        assert session.get.call_count == 1


class _FakeResumableManager:
    def __init__(self, state: NewsApiResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[NewsApiResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> NewsApiResumeConfig | None:
        return self._state

    def save_state(self, data: NewsApiResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    endpoint: str, pages_by_url: dict[str, Any], manager: _FakeResumableManager, monkeypatch: Any
) -> list[dict]:
    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        result = pages_by_url[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(news_api, "_fetch_page", fake_fetch)
    monkeypatch.setattr(news_api, "make_tracked_session", lambda: MagicMock())

    rows: list[dict] = []
    for batch in get_rows(
        api_key="k",
        endpoint=endpoint,
        query="bitcoin",
        language=None,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(batch)
    return rows


class TestGetRows:
    def test_sources_endpoint_yields_once_without_resume(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            "https://newsapi.org/v2/top-headlines/sources": {
                "status": "ok",
                "sources": [{"id": "bbc-news"}, {"id": "wired"}],
            }
        }
        rows = _collect("sources", pages, manager, monkeypatch)
        assert [r["id"] for r in rows] == ["bbc-news", "wired"]
        # Non-paginated endpoints never checkpoint — there's nothing to resume.
        assert manager.saved == []

    def test_short_page_terminates_pagination(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            "https://newsapi.org/v2/everything?q=bitcoin&pageSize=100&page=1&sortBy=publishedAt": {
                "status": "ok",
                "totalResults": 2,
                "articles": [{"url": "a"}, {"url": "b"}],
            }
        }
        rows = _collect("everything", pages, manager, monkeypatch)
        assert [r["url"] for r in rows] == ["a", "b"]
        assert manager.saved == []

    def test_walks_multiple_pages_and_checkpoints_after_each(self, monkeypatch: Any) -> None:
        full_page = [{"url": f"u{i}"} for i in range(PAGE_SIZE)]
        pages = {
            "https://newsapi.org/v2/everything?q=bitcoin&pageSize=100&page=1&sortBy=publishedAt": {
                "totalResults": 150,
                "articles": full_page,
            },
            "https://newsapi.org/v2/everything?q=bitcoin&pageSize=100&page=2&sortBy=publishedAt": {
                "totalResults": 150,
                "articles": [{"url": "last"}],
            },
        }
        manager = _FakeResumableManager()
        rows = _collect("everything", pages, manager, monkeypatch)

        assert len(rows) == PAGE_SIZE + 1
        # State is saved AFTER the first page is yielded so a crash re-yields it (merge dedupes),
        # and it points at the next page to fetch. The short final page ends the walk with no save.
        assert manager.saved == [NewsApiResumeConfig(next_page=2)]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(state=NewsApiResumeConfig(next_page=2))
        pages = {
            "https://newsapi.org/v2/everything?q=bitcoin&pageSize=100&page=2&sortBy=publishedAt": {
                "totalResults": 150,
                "articles": [{"url": "resumed"}],
            }
        }
        rows = _collect("everything", pages, manager, monkeypatch)
        # It must start at page 2 (not page 1); page-1 URL isn't in `pages`, so a KeyError would
        # signal a regression that ignored the saved cursor.
        assert [r["url"] for r in rows] == ["resumed"]

    def test_maximum_results_reached_stops_cleanly(self, monkeypatch: Any) -> None:
        # NewsAPI returns 426 `maximumResultsReached` past the reachable cap. That's a normal end of
        # the window, so the sync keeps the rows it already has instead of failing.
        cap_response = MagicMock()
        cap_response.json.return_value = {"status": "error", "code": "maximumResultsReached"}
        pages = {
            "https://newsapi.org/v2/everything?q=bitcoin&pageSize=100&page=1&sortBy=publishedAt": {
                "totalResults": 500,
                "articles": [{"url": f"u{i}"} for i in range(PAGE_SIZE)],
            },
            "https://newsapi.org/v2/everything?q=bitcoin&pageSize=100&page=2&sortBy=publishedAt": requests.HTTPError(
                response=cap_response
            ),
        }
        manager = _FakeResumableManager()
        rows = _collect("everything", pages, manager, monkeypatch)
        assert len(rows) == PAGE_SIZE

    def test_other_http_error_propagates(self, monkeypatch: Any) -> None:
        resp = MagicMock()
        resp.json.return_value = {"status": "error", "code": "parameterInvalid"}
        pages = {
            "https://newsapi.org/v2/everything?q=bitcoin&pageSize=100&page=1&sortBy=publishedAt": requests.HTTPError(
                response=resp
            ),
        }
        manager = _FakeResumableManager()
        with pytest.raises(requests.HTTPError):
            _collect("everything", pages, manager, monkeypatch)


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False)])
    def test_status_maps_to_bool(self, _name: str, status_code: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status_code)
        with patch.object(news_api, "make_tracked_session", return_value=session):
            assert validate_credentials("k") is expected

    def test_network_failure_is_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(news_api, "make_tracked_session", return_value=session):
            assert validate_credentials("k") is False


class TestSourceResponse:
    @parameterized.expand([("everything", ["url"]), ("top_headlines", ["url"]), ("sources", ["id"])])
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_keys: list[str]) -> None:
        response = news_api_source(
            api_key="k",
            endpoint=endpoint,
            query="bitcoin",
            language=None,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        # /v2/everything returns newest-first; declaring desc keeps the incremental watermark correct.
        assert response.sort_mode == "desc"

    @parameterized.expand([("everything", "publishedAt"), ("top_headlines", "publishedAt"), ("sources", None)])
    def test_partition_key_per_endpoint(self, endpoint: str, expected_partition: str | None) -> None:
        response = news_api_source(
            api_key="k",
            endpoint=endpoint,
            query="bitcoin",
            language=None,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        if expected_partition is None:
            assert response.partition_keys is None
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [expected_partition]
            assert response.partition_mode == "datetime"
