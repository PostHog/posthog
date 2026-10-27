from datetime import UTC, date, datetime
from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.newsapi import (
    NewsApiSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.news_api.news_api import (
    PAGE_SIZE,
    NewsApiResumeConfig,
    _format_from_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.news_api.source import NewsApiSource


def _driver(language: str | None = None) -> SourceDriver:
    return SourceDriver(NewsApiSource(), NewsApiSourceConfig(api_key="k", query="bitcoin", language=language))


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


class TestRequestParams:
    def test_everything_incremental_includes_from_sort_and_language(self) -> None:
        result = _driver(language="en").run(
            "everything",
            [ScriptedResponse(json={"totalResults": 1, "articles": [{"url": "a"}]})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.paths == ["/v2/everything"]
        assert result.requests[0].param("q") == "bitcoin"
        assert result.requests[0].param("sortBy") == "publishedAt"
        assert result.requests[0].param("pageSize") == str(PAGE_SIZE)
        assert result.requests[0].param("page") == "1"
        assert result.requests[0].param("language") == "en"
        assert result.requests[0].param("from") == "2026-03-04T02:58:14"

    def test_sources_ignores_query_and_pagination(self) -> None:
        # /v2/top-headlines/sources takes neither q nor pagination; only optional facet filters.
        result = _driver(language="en").run("sources", [ScriptedResponse(json={"sources": [{"id": "bbc-news"}]})])

        assert result.raised is None
        assert result.paths == ["/v2/top-headlines/sources"]
        assert result.queries == [{"language": ("en",)}]


class TestPagination:
    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "everything",
            [ScriptedResponse(json={"totalResults": 150, "articles": [{"url": "resumed"}]})],
            resume_state=NewsApiResumeConfig(next_page=2),
        )

        # It must start at page 2 (not page 1) so the saved cursor is honored.
        assert result.raised is None
        assert result.params("page") == ["2"]
        assert [row["url"] for row in result.rows] == ["resumed"]

    def test_full_page_with_missing_total_keeps_paging(self) -> None:
        # A full page with `totalResults` absent must not stop the walk. The short page 2 ends it.
        result = _driver().run(
            "everything",
            [
                ScriptedResponse(json={"articles": [{"url": f"u{i}"} for i in range(PAGE_SIZE)]}),
                ScriptedResponse(json={"articles": [{"url": "tail"}]}),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.params("page") == ["1", "2"]

    def test_other_client_error_propagates(self) -> None:
        # A 426 without `maximumResultsReached` (or any other 4xx) is a real failure — surface it.
        result = _driver().run(
            "everything", [ScriptedResponse(status=426, json={"status": "error", "code": "parameterInvalid"})]
        )

        assert isinstance(result.raised, requests.HTTPError)


class TestRetry:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_codes_retry(self, _name: str, status: int) -> None:
        result = _driver().run(
            "everything",
            [
                ScriptedResponse(status=status, json={"status": "error"}),
                ScriptedResponse(json={"totalResults": 1, "articles": [{"url": "a"}]}),
            ],
        )

        assert result.raised is None
        assert [row["url"] for row in result.rows] == ["a"]
        assert result.paths == ["/v2/everything", "/v2/everything"]

    def test_client_error_raises_without_retry(self) -> None:
        # A 401 is a permanent credential failure — it must surface at once, not burn retries.
        result = _driver().run(
            "everything", [ScriptedResponse(status=401, json={"status": "error", "code": "apiKeyInvalid"})]
        )

        assert isinstance(result.raised, requests.HTTPError)
        assert result.paths == ["/v2/everything"]


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True)])
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status, json={"sources": []})]) as network:
            assert validate_credentials("k") is expected

        assert [request.path for request in network.requests_log] == ["/v2/top-headlines/sources"]


class TestSourceResponse:
    @parameterized.expand(
        [
            # Only the incremental endpoint declares desc — the full-refresh tables have no watermark
            # to protect, so their arrival order stays on the default.
            ("everything", ["url"], "desc"),
            ("top_headlines", ["url"], "asc"),
            ("sources", ["id"], "asc"),
        ]
    )
    def test_primary_keys_and_sort_mode_per_endpoint(
        self, endpoint: str, expected_keys: list[str], expected_sort: str
    ) -> None:
        data_key = "sources" if endpoint == "sources" else "articles"
        result = _driver().run(endpoint, [ScriptedResponse(json={data_key: []})])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == expected_keys
        assert result.response.sort_mode == expected_sort

    @parameterized.expand([("everything", "publishedAt"), ("top_headlines", "publishedAt"), ("sources", None)])
    def test_partition_key_per_endpoint(self, endpoint: str, expected_partition: str | None) -> None:
        data_key = "sources" if endpoint == "sources" else "articles"
        result = _driver().run(endpoint, [ScriptedResponse(json={data_key: []})])

        assert result.raised is None
        assert result.response is not None
        if expected_partition is None:
            assert result.response.partition_keys is None
            assert result.response.partition_mode is None
        else:
            assert result.response.partition_keys == [expected_partition]
            assert result.response.partition_mode == "datetime"
