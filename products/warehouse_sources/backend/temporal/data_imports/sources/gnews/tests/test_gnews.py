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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gnews import GNewsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gnews.gnews import (
    GNewsResumeConfig,
    _build_params,
    _flatten_article,
    _format_from_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gnews.settings import GNEWS_ENDPOINTS, PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.gnews.source import GNewsSource


def _driver() -> SourceDriver:
    return SourceDriver(GNewsSource(), GNewsSourceConfig(api_key="some-key", query="posthog", category="general"))


def _page(num_articles: int, start: int = 0) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "totalArticles": 9999,
            "articles": [
                {
                    "title": f"a{start + i}",
                    "url": f"https://example.com/{start + i}",
                    "publishedAt": "2026-01-01T00:00:00Z",
                }
                for i in range(num_articles)
            ],
        }
    )


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
        with time_machine.travel("2026-06-01T00:00:00Z", tick=False):
            assert _format_from_value(value) == expected


class TestBuildParams:
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


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("missing_key_400", 400, {}, False),
            ("other_error_with_body", 422, {"errors": ["Something went wrong"]}, False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, body: dict, expected_valid: bool) -> None:
        with scripted_network([ScriptedResponse(status=status, json=body)]) as network:
            valid, message = validate_credentials("some-key")

        assert valid is expected_valid
        if not expected_valid:
            assert message
        assert network.requests_log[0].path == "/api/v4/top-headlines"
        assert network.requests_log[0].param("max") == "1"
        assert network.requests_log[0].headers["x-api-key"] == "some-key"

    def test_request_exception_returns_error(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))):
            valid, message = validate_credentials("some-key")
        assert valid is False
        assert "boom" in (message or "")


class TestCredentialHardening:
    # The API key rides in a custom X-Api-Key header, so both call sites must redact it from
    # captured samples/logs and refuse redirects (else a 30x replays the key to another host).
    # Guard the session options recorded by the real request stack.
    def test_validate_credentials_session_is_hardened(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("some-key")
        assert network.session_options == [{"redact_values": ("some-key",), "allow_redirects": False}]

    def test_get_rows_session_is_hardened(self) -> None:
        result = _driver().run("articles", [_page(1)])
        assert result.raised is None
        assert result.session_options == [{"redact_values": ("some-key",), "allow_redirects": False}]


class TestGetRows:
    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run("articles", [_page(2)], resume_state=GNewsResumeConfig(page_to_refetch=5))
        # The short page makes the request at the saved page the only request.
        assert result.params("page") == ["5"]
        assert result.raised is None

    def test_incremental_passes_from_filter(self) -> None:
        result = _driver().run(
            "articles",
            [_page(1)],
            incremental_field="publishedAt",
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )
        # from_value threaded into the params.
        assert result.params("from") == ["2026-01-01T00:00:00Z"]
        assert result.raised is None

    def test_pagination_403_beyond_first_page_stops_gracefully(self) -> None:
        # Page 1 is full (forces a page 2 request); page 2 is a plan-restricted 403.
        result = _driver().run("articles", [_page(PAGE_SIZE), ScriptedResponse(status=403)])
        # We keep page 1's rows rather than failing the whole sync.
        assert result.raised is None
        assert result.params("page") == ["1", "2"]
        assert sum(table.num_rows for table in result.rows) == PAGE_SIZE

    def test_403_on_first_page_raises(self) -> None:
        result = _driver().run("articles", [ScriptedResponse(status=403)])
        assert isinstance(result.raised, requests.HTTPError)
        assert result.params("page") == ["1"]


class TestResumableStateSaving:
    def test_state_saved_with_current_page_after_yield(self) -> None:
        # These full pages reach the batcher's yield threshold before a short final page.
        pages = [_page(2000, 0), _page(2000, 2000), _page(1, 4000)]
        result = _driver().run("articles", pages)
        saved_pages = [state.page_to_refetch for state in result.saved_states]
        # Checkpoints record the page that produced the batch (current page), never a page ahead.
        assert result.raised is None
        assert result.params("page") == ["1", "2", "3"]
        assert 1 in saved_pages
        assert 2 in saved_pages
        assert max(saved_pages) <= 2
        assert result.committed_states == [GNewsResumeConfig(page_to_refetch=1), GNewsResumeConfig(page_to_refetch=2)]


class TestGnewsSource:
    @parameterized.expand([("articles",), ("top_headlines",)])
    def test_source_response_contract(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_page(0)])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["url"]
        # GNews only offers newest-first ordering; asc would corrupt the incremental watermark.
        assert response.sort_mode == "desc"
        assert response.partition_keys == ["publishedAt"]
        assert response.partition_mode == "datetime"
