from datetime import UTC, date, datetime
from typing import Any

import time_machine

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.newyorktimes import (
    NewYorkTimesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.new_york_times.new_york_times import (
    ARTICLE_SEARCH_MAX_PAGES,
    NewYorkTimesResumeConfig,
    NewYorkTimesRetryableError,
    _format_begin_date,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.new_york_times.source import NewYorkTimesSource


def _driver(article_search_query: str | None = None) -> SourceDriver:
    return SourceDriver(
        NewYorkTimesSource(), NewYorkTimesSourceConfig(api_key="KEY", article_search_query=article_search_query)
    )


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


class TestValidateCredentials:
    @parameterized.expand(
        [
            # A 403 means the key is genuine but the app hasn't enabled this API — must not block create.
            ("forbidden", 403, True),
            ("rate_limited", 429, True),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("KEY") is expected
        assert network.requests_log[0].path == "/svc/mostpopular/v2/viewed/1.json"
        assert network.requests_log[0].param("api-key") == "KEY"


class TestGetRowsSnapshot:
    def test_single_request_yields_results(self) -> None:
        result = _driver().run("top_stories", [ScriptedResponse(json={"results": [{"uri": "u1"}, {"uri": "u2"}]})])

        assert result.raised is None
        assert result.items == [[{"uri": "u1"}, {"uri": "u2"}]]
        assert result.paths == ["/svc/topstories/v2/home.json"]


class TestGetRowsArticleSearch:
    @staticmethod
    def _docs(n: int, start: int = 0) -> dict[str, object]:
        return {"response": {"docs": [{"_id": f"a{start + i}"} for i in range(n)]}}

    def test_pages_until_short_page_and_saves_state(self) -> None:
        # A full page (10) then a short page (2) → two fetches, then stop.
        with time_machine.travel("2026-07-02", tick=False):
            result = _driver().run(
                "article_search",
                [ScriptedResponse(json=self._docs(10, 0)), ScriptedResponse(json=self._docs(2, 10))],
            )

        assert result.raised is None
        assert [len(batch) for batch in result.items] == [10, 2]
        assert result.params("page") == ["0", "1"]
        # State saved after each yielded page, advancing the page cursor with a stable begin_date.
        assert result.saved_states == [
            NewYorkTimesResumeConfig(page=1, begin_date="20260602"),
            NewYorkTimesResumeConfig(page=2, begin_date="20260602"),
        ]
        assert result.committed_states == [NewYorkTimesResumeConfig(page=1, begin_date="20260602")]

    def test_respects_page_cap(self) -> None:
        # Always-full pages must stop at the 100-page hard cap rather than loop forever.
        with time_machine.travel("2026-07-02", tick=False):
            result = _driver().run("article_search", always(ScriptedResponse(json=self._docs(10, 0))))

        assert result.raised is None
        assert len(result.items) == ARTICLE_SEARCH_MAX_PAGES
        assert len(result.requests) == ARTICLE_SEARCH_MAX_PAGES
        assert result.params("page") == [str(page) for page in range(ARTICLE_SEARCH_MAX_PAGES)]

    def test_resumes_from_saved_page_and_window(self) -> None:
        result = _driver().run(
            "article_search",
            [ScriptedResponse(json={"response": {"docs": []}})],
            resume_state=NewYorkTimesResumeConfig(page=7, begin_date="20250101"),
        )

        assert result.raised is None
        assert result.params("page") == ["7"]
        assert result.params("begin_date") == ["20250101"]

    def test_passes_query_and_sort(self) -> None:
        with time_machine.travel("2026-07-02", tick=False):
            result = _driver("climate").run(
                "article_search",
                [ScriptedResponse(json={"response": {"docs": []}})],
                incremental_field="pub_date",
                db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
            )

        assert result.raised is None
        assert result.params("sort") == ["oldest"]
        assert result.params("q") == ["climate"]
        assert result.params("begin_date") == ["20260601"]


class TestFetchPageRetry:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_statuses_retry(self, _name: str, status_code: int) -> None:
        result = _driver().run(
            "top_stories",
            [ScriptedResponse(status=status_code), ScriptedResponse(json={"results": [{"uri": "u1"}]})],
        )

        assert result.raised is None
        assert result.rows == [{"uri": "u1"}]
        assert result.paths == ["/svc/topstories/v2/home.json"] * 2

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_persistent_retryable_status_raises_retryable_error(self, _name: str, status_code: int) -> None:
        result = _driver().run("top_stories", always(ScriptedResponse(status=status_code)))

        assert isinstance(result.raised, NewYorkTimesRetryableError)

    def test_client_error_raises_without_leaking_api_key(self) -> None:
        # The api-key rides in the query string; a client-error must never surface it in the raised
        # message (it's stored on the schema and shown to users). The message must still start with the
        # non-retryable-error key prefix so the sync stops instead of retrying forever.
        driver = SourceDriver(NewYorkTimesSource(), NewYorkTimesSourceConfig(api_key="SECRETKEY"))
        result = driver.run("top_stories", [ScriptedResponse(status=401)])

        assert isinstance(result.raised, requests.HTTPError)
        message = str(result.raised)
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
        body: dict[str, Any] = {"response": {"docs": []}} if endpoint == "article_search" else {"results": []}
        result = _driver().run(endpoint, [ScriptedResponse(json=body)])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"
