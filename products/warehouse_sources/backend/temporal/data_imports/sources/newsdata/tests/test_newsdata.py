from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.newsdata import newsdata
from products.warehouse_sources.backend.temporal.data_imports.sources.newsdata.newsdata import (
    NewsDataResumeConfig,
    NewsDataRetryableError,
    _build_query_params,
    _page_url,
    _raise_for_error_body,
    _to_from_date,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.newsdata.settings import NEWSDATA_ENDPOINTS


class TestToFromDate:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2024, 1, 15, 12, 34, 56, tzinfo=UTC), "2024-01-15"),
            ("naive_datetime", datetime(2024, 1, 15, 12, 34, 56), "2024-01-15"),
            ("date_value", date(2024, 1, 15), "2024-01-15"),
            ("api_string", "2024-01-15 12:34:56", "2024-01-15"),
            ("none", None, None),
        ]
    )
    def test_to_from_date(self, _name: str, value: Any, expected: str | None) -> None:
        assert _to_from_date(value) == expected


class TestBuildQueryParams:
    @parameterized.expand(
        [
            # /latest and /sources reject from_date/to_date entirely, so we must never send them —
            # doing so 4xxs the whole sync with UnsupportedParameter.
            ("latest_incremental", "latest", True, datetime(2024, 1, 15, tzinfo=UTC)),
            ("sources_incremental", "sources", True, datetime(2024, 1, 15, tzinfo=UTC)),
            # A date-filter endpoint syncing full-refresh sends no window either.
            ("archive_full_refresh", "archive", False, datetime(2024, 1, 15, tzinfo=UTC)),
        ]
    )
    def test_no_from_date(self, _name: str, endpoint: str, incremental: bool, watermark: Any) -> None:
        params = _build_query_params(NEWSDATA_ENDPOINTS[endpoint], incremental, watermark)
        assert "from_date" not in params

    @parameterized.expand([("archive",), ("crypto",)])
    def test_incremental_uses_watermark_date(self, endpoint: str) -> None:
        params = _build_query_params(NEWSDATA_ENDPOINTS[endpoint], True, datetime(2024, 3, 4, 2, 58, 14, tzinfo=UTC))
        assert params == {"from_date": "2024-03-04"}

    @parameterized.expand([("archive",), ("crypto",)])
    @freeze_time("2026-06-15T12:00:00Z")
    def test_first_sync_applies_lookback_floor(self, endpoint: str) -> None:
        # Without a watermark the first sync must floor at the trailing lookback window instead of
        # crawling the entire (up to 7-year) archive.
        params = _build_query_params(NEWSDATA_ENDPOINTS[endpoint], True, None)
        assert params == {"from_date": "2026-05-16"}


class TestPageUrl:
    def test_cursor_added_as_page_param(self) -> None:
        url = _page_url(NEWSDATA_ENDPOINTS["latest"], {}, "cursor_token_abc")
        assert url == "https://newsdata.io/api/1/latest?page=cursor_token_abc"

    def test_no_cursor_on_first_page(self) -> None:
        assert _page_url(NEWSDATA_ENDPOINTS["latest"], {}, None) == "https://newsdata.io/api/1/latest"

    def test_query_params_and_cursor_combine(self) -> None:
        url = _page_url(NEWSDATA_ENDPOINTS["archive"], {"from_date": "2024-01-01"}, "tok")
        assert url == "https://newsdata.io/api/1/archive?from_date=2024-01-01&page=tok"

    def test_api_key_never_in_url(self) -> None:
        # The key travels in the X-ACCESS-KEY header, never the URL, so it can't leak into request logs.
        url = _page_url(NEWSDATA_ENDPOINTS["archive"], {"from_date": "2024-01-01"}, "tok")
        assert "apikey" not in url and "ACCESS" not in url


class TestRaiseForErrorBody:
    def test_error_status_raises(self) -> None:
        # NewsData reports hard failures (unsupported param, quota exhausted) in a 200-body envelope.
        with pytest.raises(NewsDataRetryableError):
            _raise_for_error_body(
                {"status": "error", "results": {"message": "quota exceeded", "code": "TooManyRequests"}},
                "https://newsdata.io/api/1/latest",
            )

    def test_success_status_is_noop(self) -> None:
        _raise_for_error_body({"status": "success", "results": []}, "https://newsdata.io/api/1/latest")


class _FakeResumableManager:
    def __init__(self, state: NewsDataResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[NewsDataResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> NewsDataResumeConfig | None:
        return self._state

    def save_state(self, data: NewsDataResumeConfig) -> None:
        self.saved.append(data)


def _collect(manager: _FakeResumableManager, monkeypatch: Any, endpoint: str, pages: dict[str, Any], **kwargs: Any):
    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(newsdata, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for batch in get_rows(
        api_key="pub_test", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=manager, **kwargs
    ):
        rows.extend(batch)
    return rows


class TestGetRowsPagination:
    def test_follows_next_page_until_absent(self, monkeypatch: Any) -> None:
        pages = {
            "https://newsdata.io/api/1/latest": {
                "status": "success",
                "results": [{"article_id": "a1"}],
                "nextPage": "p2",
            },
            "https://newsdata.io/api/1/latest?page=p2": {
                "status": "success",
                "results": [{"article_id": "a2"}],
                "nextPage": None,
            },
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, "latest", pages)
        assert [r["article_id"] for r in rows] == ["a1", "a2"]

    def test_sources_endpoint_never_paginates(self, monkeypatch: Any) -> None:
        # /sources rejects the `page` param, so even a stray nextPage in the body must not trigger a
        # second request.
        fetched: list[str] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            fetched.append(url)
            return {"status": "success", "results": [{"id": "bbc"}], "nextPage": "should_be_ignored"}

        monkeypatch.setattr(newsdata, "_fetch_page", fake_fetch)
        rows = list(
            get_rows(
                api_key="pub_test",
                endpoint="sources",
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),
            )
        )

        assert fetched == ["https://newsdata.io/api/1/sources"]
        assert [r["id"] for batch in rows for r in batch] == ["bbc"]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        pages = {
            "https://newsdata.io/api/1/latest?page=saved_cursor": {
                "status": "success",
                "results": [{"article_id": "a3"}],
                "nextPage": None,
            },
        }
        manager = _FakeResumableManager(NewsDataResumeConfig(next_page="saved_cursor"))
        rows = _collect(manager, monkeypatch, "latest", pages)
        assert [r["article_id"] for r in rows] == ["a3"]

    def test_saves_cursor_after_yielding_batch(self, monkeypatch: Any) -> None:
        # With a tiny batch threshold each page fills a batch, so state is persisted after the yield
        # (never before) — a crash re-yields the last batch rather than skipping ahead.
        monkeypatch.setattr(newsdata, "_BATCH_SIZE", 1)
        pages = {
            "https://newsdata.io/api/1/latest": {
                "status": "success",
                "results": [{"article_id": "a1"}],
                "nextPage": "p2",
            },
            "https://newsdata.io/api/1/latest?page=p2": {
                "status": "success",
                "results": [{"article_id": "a2"}],
                "nextPage": None,
            },
        }
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, "latest", pages)
        # Only the first page has a following page, so exactly one cursor is saved, pointing at it.
        assert [s.next_page for s in manager.saved] == ["p2"]


def _response_with_status(status_code: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    return response


class TestFetchPageRetries:
    @parameterized.expand(
        [
            ("rate_limited", 429),
            ("server_error", 500),
            ("bad_gateway", 502),
        ]
    )
    def test_retryable_status_codes_retry(self, _name: str, status_code: int) -> None:
        throttled = MagicMock()
        throttled.status_code = status_code
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"status": "success", "results": []}

        session = MagicMock()
        session.get.side_effect = [throttled, good]

        with patch.object(newsdata._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = newsdata._fetch_page(session, "https://newsdata.io/api/1/latest", {}, MagicMock())

        assert result == {"status": "success", "results": []}
        assert session.get.call_count == 2

    @parameterized.expand(
        [
            ("read_timeout", requests.ReadTimeout("Read timed out.")),
            ("connection_error", requests.ConnectionError("Connection reset by peer")),
            ("chunked", requests.exceptions.ChunkedEncodingError("Connection broken")),
        ]
    )
    def test_transient_errors_retry(self, _name: str, transient: Exception) -> None:
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"status": "success", "results": []}

        session = MagicMock()
        session.get.side_effect = [transient, good]

        with patch.object(newsdata._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = newsdata._fetch_page(session, "https://newsdata.io/api/1/latest", {}, MagicMock())

        assert result == {"status": "success", "results": []}
        assert session.get.call_count == 2

    def test_unauthorized_is_not_retried(self) -> None:
        # A 401 is a permanent credential failure: raise_for_status must surface it immediately so
        # get_non_retryable_errors can disable the source, not burn five retries.
        unauthorized = MagicMock()
        unauthorized.status_code = 401
        unauthorized.ok = False
        unauthorized.raise_for_status.side_effect = requests.HTTPError("401 Client Error: Unauthorized")

        session = MagicMock()
        session.get.return_value = unauthorized

        with pytest.raises(requests.HTTPError):
            newsdata._fetch_page(session, "https://newsdata.io/api/1/latest", {}, MagicMock())

        assert session.get.call_count == 1


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_bool(self, _name: str, status_code: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response

        with patch.object(newsdata, "make_tracked_session", return_value=session):
            assert validate_credentials("pub_test") is expected

    def test_network_failure_is_false(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")

        with patch.object(newsdata, "make_tracked_session", return_value=session):
            assert validate_credentials("pub_test") is False
