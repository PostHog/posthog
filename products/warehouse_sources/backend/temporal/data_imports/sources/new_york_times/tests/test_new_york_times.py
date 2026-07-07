from datetime import UTC, date, datetime

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.new_york_times import new_york_times
from products.warehouse_sources.backend.temporal.data_imports.sources.new_york_times.new_york_times import (
    ARTICLE_SEARCH_MAX_PAGES,
    NewYorkTimesResumeConfig,
    _build_url,
    _format_begin_date,
    _resolve_begin_date,
    _select_rows,
    get_rows,
    new_york_times_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.new_york_times.settings import (
    NEW_YORK_TIMES_ENDPOINTS,
)


class _FakeResumableManager:
    def __init__(self, state: NewYorkTimesResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[NewYorkTimesResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> NewYorkTimesResumeConfig | None:
        return self._state

    def save_state(self, data: NewYorkTimesResumeConfig) -> None:
        self.saved.append(data)


class TestFormatBeginDate:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "20260304"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "20260304"),
            ("date_value", date(2026, 1, 15), "20260115"),
            ("string_passthrough", "20250101", "20250101"),
        ]
    )
    def test_format_begin_date(self, _name: str, value: object, expected: str) -> None:
        assert _format_begin_date(value) == expected


class TestResolveBeginDate:
    @freeze_time("2026-07-02")
    def test_uses_watermark_when_incremental(self) -> None:
        config = NEW_YORK_TIMES_ENDPOINTS["article_search"]
        assert _resolve_begin_date(config, True, datetime(2026, 6, 1, tzinfo=UTC)) == "20260601"

    @freeze_time("2026-07-02")
    def test_falls_back_to_lookback_without_watermark(self) -> None:
        # First incremental sync (no watermark) must window to the lookback range, not all of history.
        config = NEW_YORK_TIMES_ENDPOINTS["article_search"]
        assert _resolve_begin_date(config, True, None) == "20260602"

    @freeze_time("2026-07-02")
    def test_full_refresh_uses_lookback(self) -> None:
        config = NEW_YORK_TIMES_ENDPOINTS["article_search"]
        assert _resolve_begin_date(config, False, None) == "20260602"


class TestSelectRows:
    def test_article_search_reads_nested_docs(self) -> None:
        config = NEW_YORK_TIMES_ENDPOINTS["article_search"]
        data = {"response": {"docs": [{"_id": "a"}, {"_id": "b"}]}}
        assert _select_rows(config, data) == [{"_id": "a"}, {"_id": "b"}]

    def test_snapshot_reads_results(self) -> None:
        config = NEW_YORK_TIMES_ENDPOINTS["top_stories"]
        data = {"results": [{"uri": "x"}]}
        assert _select_rows(config, data) == [{"uri": "x"}]

    def test_missing_key_returns_empty(self) -> None:
        config = NEW_YORK_TIMES_ENDPOINTS["article_search"]
        assert _select_rows(config, {"response": {}}) == []


class TestBuildUrl:
    def test_includes_api_key_and_encodes_params(self) -> None:
        url = _build_url("/svc/search/v2/articlesearch.json", "KEY", {"q": "a b", "page": 0})
        assert url.startswith("https://api.nytimes.com/svc/search/v2/articlesearch.json?")
        assert "q=a+b" in url
        assert "page=0" in url
        assert "api-key=KEY" in url


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            # A 403 means the key is genuine but the app hasn't enabled this API — must not block create.
            ("forbidden", 403, True),
            ("rate_limited", 429, True),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response
        with patch.object(new_york_times, "make_tracked_session", return_value=session):
            assert validate_credentials("KEY") is expected

    def test_network_error_is_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(new_york_times, "make_tracked_session", return_value=session):
            assert validate_credentials("KEY") is False


def _mock_response(status_code: int, body: dict) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = body
    return response


class TestGetRowsSnapshot:
    def test_single_request_yields_results(self) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(200, {"results": [{"uri": "u1"}, {"uri": "u2"}]})
        with patch.object(new_york_times, "make_tracked_session", return_value=session):
            batches = list(
                get_rows("KEY", "top_stories", MagicMock(), _FakeResumableManager())  # type: ignore[arg-type]
            )
        assert batches == [[{"uri": "u1"}, {"uri": "u2"}]]
        assert session.get.call_count == 1

    def test_empty_results_yields_nothing(self) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(200, {"results": []})
        with patch.object(new_york_times, "make_tracked_session", return_value=session):
            batches = list(
                get_rows("KEY", "most_popular_viewed", MagicMock(), _FakeResumableManager())  # type: ignore[arg-type]
            )
        assert batches == []


class TestGetRowsArticleSearch:
    @staticmethod
    def _docs(n: int, start: int = 0) -> dict:
        return {"response": {"docs": [{"_id": f"a{start + i}"} for i in range(n)]}}

    def test_pages_until_short_page_and_saves_state(self) -> None:
        # A full page (10) then a short page (2) → two fetches, then stop.
        session = MagicMock()
        session.get.side_effect = [
            _mock_response(200, self._docs(10, 0)),
            _mock_response(200, self._docs(2, 10)),
        ]
        manager = _FakeResumableManager()
        with (
            patch.object(new_york_times, "make_tracked_session", return_value=session),
            patch.object(new_york_times.time, "sleep"),
            freeze_time("2026-07-02"),
        ):
            batches = list(
                get_rows("KEY", "article_search", MagicMock(), manager)  # type: ignore[arg-type]
            )
        assert len(batches) == 2
        assert len(batches[0]) == 10
        assert len(batches[1]) == 2
        # State saved after each yielded page, advancing the page cursor with a stable begin_date.
        assert [s.page for s in manager.saved] == [1, 2]
        assert all(s.begin_date == "20260602" for s in manager.saved)

    def test_stops_on_empty_first_page(self) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(200, {"response": {"docs": []}})
        with (
            patch.object(new_york_times, "make_tracked_session", return_value=session),
            patch.object(new_york_times.time, "sleep"),
            freeze_time("2026-07-02"),
        ):
            batches = list(
                get_rows("KEY", "article_search", MagicMock(), _FakeResumableManager())  # type: ignore[arg-type]
            )
        assert batches == []
        assert session.get.call_count == 1

    def test_respects_page_cap(self) -> None:
        # Always-full pages must stop at the 100-page hard cap rather than loop forever.
        session = MagicMock()
        session.get.return_value = _mock_response(200, self._docs(10, 0))
        with (
            patch.object(new_york_times, "make_tracked_session", return_value=session),
            patch.object(new_york_times.time, "sleep"),
            freeze_time("2026-07-02"),
        ):
            batches = list(
                get_rows("KEY", "article_search", MagicMock(), _FakeResumableManager())  # type: ignore[arg-type]
            )
        assert len(batches) == ARTICLE_SEARCH_MAX_PAGES
        assert session.get.call_count == ARTICLE_SEARCH_MAX_PAGES

    def test_resumes_from_saved_page_and_window(self) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(200, {"response": {"docs": []}})
        manager = _FakeResumableManager(NewYorkTimesResumeConfig(page=7, begin_date="20250101"))
        with (
            patch.object(new_york_times, "make_tracked_session", return_value=session),
            patch.object(new_york_times.time, "sleep"),
        ):
            list(get_rows("KEY", "article_search", MagicMock(), manager))  # type: ignore[arg-type]
        called_url = session.get.call_args_list[0].args[0]
        assert "page=7" in called_url
        assert "begin_date=20250101" in called_url

    def test_passes_query_and_sort(self) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(200, {"response": {"docs": []}})
        with (
            patch.object(new_york_times, "make_tracked_session", return_value=session),
            patch.object(new_york_times.time, "sleep"),
            freeze_time("2026-07-02"),
        ):
            list(
                get_rows(
                    "KEY",
                    "article_search",
                    MagicMock(),
                    _FakeResumableManager(),  # type: ignore[arg-type]
                    query="climate",
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
                )
            )
        called_url = session.get.call_args_list[0].args[0]
        assert "sort=oldest" in called_url
        assert "q=climate" in called_url
        assert "begin_date=20260601" in called_url


class TestFetchPageRetry:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_statuses_retry(self, _name: str, status_code: int) -> None:
        bad = _mock_response(status_code, {})
        good = _mock_response(200, {"results": []})
        session = MagicMock()
        session.get.side_effect = [bad, good]
        with patch.object(new_york_times._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = new_york_times._fetch_page(session, "https://api.nytimes.com/x", {}, MagicMock())
        assert result == {"results": []}
        assert session.get.call_count == 2

    def test_client_error_raises_without_leaking_api_key(self) -> None:
        # The api-key rides in the query string; a client-error must never surface it in the raised
        # message (it's stored on the schema and shown to users). The message must still start with the
        # non-retryable-error key prefix so the sync stops instead of retrying forever.
        session = MagicMock()
        response = requests.Response()
        response.status_code = 401
        response.reason = "Unauthorized"
        session.get.return_value = response
        url = new_york_times._build_url("/svc/mostpopular/v2/viewed/7.json", "SECRETKEY", {})
        with pytest.raises(requests.HTTPError) as exc_info:
            new_york_times._fetch_page(session, url, {}, MagicMock())
        message = str(exc_info.value)
        assert "SECRETKEY" not in message
        assert message.startswith("401 Client Error: Unauthorized for url: https://api.nytimes.com")


class TestSourceResponse:
    @parameterized.expand(
        [
            ("article_search", ["_id"], "pub_date"),
            ("most_popular_viewed", ["uri"], "published_date"),
            ("most_popular_emailed", ["uri"], "published_date"),
            ("most_popular_shared", ["uri"], "published_date"),
            ("top_stories", ["uri"], "created_date"),
        ]
    )
    def test_response_metadata(self, endpoint: str, primary_keys: list[str], partition_key: str) -> None:
        response = new_york_times_source("KEY", endpoint, MagicMock(), _FakeResumableManager())  # type: ignore[arg-type]
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"

    def test_items_callable_is_lazy(self) -> None:
        # Building the SourceResponse must not make any HTTP calls — only iterating `items` does.
        with patch.object(new_york_times, "make_tracked_session") as mocked:
            response = new_york_times_source("KEY", "top_stories", MagicMock(), _FakeResumableManager())  # type: ignore[arg-type]
            assert mocked.call_count == 0
            assert callable(response.items)


@pytest.mark.parametrize("endpoint", list(NEW_YORK_TIMES_ENDPOINTS.keys()))
def test_every_endpoint_declares_primary_keys(endpoint: str) -> None:
    config = NEW_YORK_TIMES_ENDPOINTS[endpoint]
    assert config.primary_keys, f"{endpoint} must declare primary keys"
    assert config.data_selector in {"docs", "results"}
