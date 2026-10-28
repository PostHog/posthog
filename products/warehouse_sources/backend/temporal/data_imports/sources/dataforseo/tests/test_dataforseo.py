from typing import Any

import pytest
from unittest.mock import MagicMock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dataforseo.dataforseo import (
    DATAFORSEO_BASE_URL,
    MAX_PAGES_PER_TARGET,
    PAGE_SIZE,
    DataForSEOAPIError,
    DataForSEOResumeConfig,
    DataForSEORetryableError,
    _raise_for_body_status,
    _request_task,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dataforseo.settings import (
    DATAFORSEO_ENDPOINTS,
    ENDPOINTS,
    KEYWORD_SCOPES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dataforseo.source import DataForSEOSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dataforseo import (
    DataForSEOSourceConfig,
)

TARGETED_ENDPOINTS = [name for name, config in DATAFORSEO_ENDPOINTS.items() if config.scope == "target"]
UNTARGETED_ENDPOINTS = [name for name, config in DATAFORSEO_ENDPOINTS.items() if config.scope != "target"]
KEYWORD_ENDPOINTS = [name for name, config in DATAFORSEO_ENDPOINTS.items() if config.scope in KEYWORD_SCOPES]


def _resp(body: Any, status: int = 200) -> Any:
    response = MagicMock()
    response.status_code = status
    response.ok = 200 <= status < 400
    response.json.return_value = body
    response.text = str(body)
    return response


def _body(
    results: list[dict[str, Any]] | None,
    status_code: int = 20000,
    task_status_code: int = 20000,
) -> dict[str, Any]:
    return {
        "status_code": status_code,
        "status_message": "Ok.",
        "tasks": [{"status_code": task_status_code, "status_message": "Ok.", "result": results}],
    }


def _items_result(items: list[dict[str, Any]], total_count: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"target": "example.com", "items": items, "items_count": len(items)}
    if total_count is not None:
        result["total_count"] = total_count
    return result


def _driver(targets: str = "example.com", keywords: str | None = None) -> SourceDriver:
    config = DataForSEOSourceConfig(api_login="login", api_password="password", targets=targets, keywords=keywords)
    return SourceDriver(DataForSEOSource(), config)


def _answer(results: list[dict[str, Any]] | None, status_code: int = 20000) -> ScriptedResponse:
    return ScriptedResponse(json=_body(results, status_code=status_code))


class TestBodyStatusClassification:
    @pytest.mark.parametrize("status_code", [40202, 50000, 50401])
    def test_transient_codes_raise_retryable(self, status_code: int) -> None:
        with pytest.raises(DataForSEORetryableError):
            _raise_for_body_status(status_code, "try again")

    @pytest.mark.parametrize("status_code", [40100, 40200, 40201, 40203, 40210, 40501])
    def test_permanent_codes_raise_api_error_with_code(self, status_code: int) -> None:
        with pytest.raises(DataForSEOAPIError, match=rf"\[{status_code}\]"):
            _raise_for_body_status(status_code, "nope")


class TestRequestTask:
    # Exercise a single attempt via __wrapped__ so the tenacity retry loop (and its real
    # backoff sleeps) is not driven.
    def _post(self, response: Any) -> list[dict[str, Any]]:
        session = MagicMock()
        session.post.return_value = response
        return _request_task.__wrapped__(  # type: ignore[attr-defined]
            session, "POST", "/dataforseo_labs/google/ranked_keywords/live", {"target": "example.com"}, MagicMock()
        )

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_http_statuses_raise_retryable_error(self, status: int) -> None:
        with pytest.raises(DataForSEORetryableError):
            self._post(_resp({}, status=status))

    def test_client_error_raises_http_error(self) -> None:
        response = _resp({}, status=401)
        response.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=response)
        with pytest.raises(requests.HTTPError):
            self._post(response)

    def test_top_level_error_code_raises(self) -> None:
        with pytest.raises(DataForSEOAPIError, match=r"\[40100\]"):
            self._post(_resp({"status_code": 40100, "status_message": "unauthorized", "tasks": []}))

    def test_task_level_error_code_raises(self) -> None:
        with pytest.raises(DataForSEOAPIError, match=r"\[40501\]"):
            self._post(_resp(_body(None, task_status_code=40501)))

    @pytest.mark.parametrize("results", [None, []])
    def test_missing_result_returns_empty(self, results: Any) -> None:
        assert self._post(_resp(_body(results))) == []


class TestGetRows:
    def test_items_endpoint_injects_target(self) -> None:
        result = _driver().run(
            "domain_rank_overview", [_answer([_items_result([{"se_type": "google", "metrics": {}}])])]
        )

        assert result.urls == [f"{DATAFORSEO_BASE_URL}/dataforseo_labs/google/domain_rank_overview/live"]
        assert result.items == [[{"se_type": "google", "metrics": {}, "target": "example.com"}]]

    def test_backlinks_payload_has_no_location_and_includes_subdomains(self) -> None:
        summary = {"target": "example.com", "rank": 312, "backlinks": 100}
        result = _driver().run("backlinks_summary", [_answer([summary])])

        payload = result.requests[0].json()[0]
        assert "location_name" not in payload
        assert payload["include_subdomains"] is True
        assert result.items == [[{**summary, "target": "example.com"}]]

    def test_historical_payload_requests_full_history_and_rows_carry_date(self) -> None:
        items = [{"year": 2024, "month": 3, "metrics": {}}, {"year": 2024, "month": 11, "metrics": {}}]
        result = _driver().run("historical_rank_overview", [_answer([_items_result(items)])])

        assert result.requests[0].json()[0]["date_from"] == "2020-10-01"
        assert [row["date"] for row in result.rows] == ["2024-03-01", "2024-11-01"]

    def test_ranked_keywords_skips_items_without_keyword(self) -> None:
        items: list[dict[str, Any]] = [{"keyword_data": {}}, {"keyword_data": {"keyword": "ok"}}]
        result = _driver().run("ranked_keywords", [_answer([_items_result(items, total_count=2)])])

        assert [row["keyword"] for row in result.rows] == ["ok"]

    def test_pagination_stops_at_page_cap(self) -> None:
        logger = MagicMock()
        full_page = [{"keyword_data": {"keyword": f"kw{i}"}} for i in range(PAGE_SIZE)]
        result = _driver().run(
            "ranked_keywords",
            [_answer([_items_result(full_page, total_count=PAGE_SIZE * 100)]) for _ in range(MAX_PAGES_PER_TARGET)],
            logger=logger,
        )

        assert len(result.requests) == MAX_PAGES_PER_TARGET
        assert len(result.items) == MAX_PAGES_PER_TARGET
        logger.warning.assert_called_once()

    def test_resume_skips_earlier_targets_and_seeds_offset(self) -> None:
        result = _driver(targets="a.com, b.com").run(
            "ranked_keywords",
            [_answer([_items_result([{"keyword_data": {"keyword": "kw"}}], total_count=1)])],
            resume_state=DataForSEOResumeConfig(target="b.com", offset=PAGE_SIZE),
        )

        assert len(result.requests) == 1
        assert result.requests[0].json()[0]["target"] == "b.com"
        assert result.requests[0].json()[0]["offset"] == PAGE_SIZE

    def test_session_carries_basic_auth_and_redacts_password(self) -> None:
        result = _driver().run("domain_rank_overview", [_answer([_items_result([])])])

        assert result.requests[0].headers["authorization"].startswith("Basic ")
        assert "password" in result.session_options[0]["redact_values"]

    @pytest.mark.parametrize(
        ("endpoint", "path", "expected_payload"),
        [
            (
                "relevant_pages",
                "/dataforseo_labs/google/relevant_pages/live",
                {
                    "target": "example.com",
                    "location_name": "United States",
                    "language_name": "English",
                    "limit": PAGE_SIZE,
                    "offset": 0,
                },
            ),
            (
                "backlinks_referring_domains",
                "/backlinks/referring_domains/live",
                {"target": "example.com", "include_subdomains": True, "limit": PAGE_SIZE, "offset": 0},
            ),
            (
                "backlinks",
                "/backlinks/backlinks/live",
                {
                    "target": "example.com",
                    "include_subdomains": True,
                    "order_by": ["rank,desc"],
                    "limit": PAGE_SIZE,
                    "offset": 0,
                },
            ),
            (
                "backlinks_anchors",
                "/backlinks/anchors/live",
                {
                    "target": "example.com",
                    "include_subdomains": True,
                    "order_by": ["backlinks,desc"],
                    "limit": PAGE_SIZE,
                    "offset": 0,
                },
            ),
            ("backlinks_history", "/backlinks/history/live", {"target": "example.com"}),
            (
                "backlinks_timeseries_summary",
                "/backlinks/timeseries_summary/live",
                {
                    "target": "example.com",
                    "date_from": "2019-01-30",
                    "group_range": "month",
                    "include_subdomains": True,
                },
            ),
        ],
    )
    def test_request_shape_per_endpoint(self, endpoint: str, path: str, expected_payload: dict[str, Any]) -> None:
        # The Backlinks API rejects the Labs location/language fields, and neither trend endpoint
        # accepts limit/offset, so the payload each endpoint sends is asserted in full.
        item = {
            "date": "2020-08-31 00:00:00 +00:00",
            "domain": "news.example",
            "page_address": "https://example.com/a",
        }
        result = _driver().run(endpoint, [_answer([_items_result([item], total_count=1)])])

        assert [(request.url, request.json()[0]) for request in result.requests] == [
            (f"{DATAFORSEO_BASE_URL}{path}", expected_payload)
        ]
        assert result.items == [[{**item, "target": "example.com"}]]

    def test_historical_search_volume_sends_every_keyword_in_one_request(self) -> None:
        item = {
            "se_type": "google",
            "keyword": "posthog",
            "location_code": 2840,
            "language_code": "en",
            "search_partners": False,
            "keyword_info": {
                "search_volume": 1000,
                "monthly_searches": [
                    {"year": 2024, "month": 7, "search_volume": 450},
                    {"year": 2024, "month": 6, "search_volume": 300},
                ],
            },
        }
        result = _driver(targets="a.com, b.com", keywords="posthog, session replay").run(
            "historical_search_volume",
            [_answer([_items_result([item])])],
        )

        # The endpoint takes the whole keyword list, and has no target fan-out to repeat it over.
        assert [(request.url, request.json()[0]) for request in result.requests] == [
            (
                f"{DATAFORSEO_BASE_URL}/dataforseo_labs/google/historical_search_volume/live",
                {
                    "keywords": ["posthog", "session replay"],
                    "location_name": "United States",
                    "language_name": "English",
                },
            )
        ]
        assert result.items == [
            [
                {
                    "keyword": "posthog",
                    "se_type": "google",
                    "location_code": 2840,
                    "language_code": "en",
                    "search_partners": False,
                    "year": 2024,
                    "month": 7,
                    "date": "2024-07-01",
                    "search_volume": 450,
                },
                {
                    "keyword": "posthog",
                    "se_type": "google",
                    "location_code": 2840,
                    "language_code": "en",
                    "search_partners": False,
                    "year": 2024,
                    "month": 6,
                    "date": "2024-06-01",
                    "search_volume": 300,
                },
            ]
        ]
        assert result.saved_states == []

    @pytest.mark.parametrize(
        "item",
        [
            {"keyword": "posthog", "keyword_info": {}},
            {"keyword": "posthog", "keyword_info": {"monthly_searches": [{"year": None, "month": 6}]}},
            {"keyword": None, "keyword_info": {"monthly_searches": [{"year": 2024, "month": 6}]}},
        ],
    )
    def test_historical_search_volume_skips_rows_it_cannot_key(self, item: dict[str, Any]) -> None:
        # keyword, year and month are the primary key and year/month also derive the partition
        # column, so a row missing any of them has nowhere to land.
        result = _driver(keywords="posthog").run("historical_search_volume", [_answer([_items_result([item])])])

        assert result.items == []

    def test_serp_organic_fans_out_per_keyword_and_stamps_crawl_metadata(self) -> None:
        result = {
            "keyword": "posthog",
            "se_domain": "google.com",
            "location_code": 2840,
            "language_code": "en",
            "check_url": "https://www.google.com/search?q=posthog",
            "datetime": "2024-08-11 13:24:34 +00:00",
            "items_count": 1,
            "items": [{"type": "organic", "rank_absolute": 1, "domain": "posthog.com"}],
        }
        driven = _driver(keywords="posthog, session replay").run(
            "serp_organic",
            [_answer([result]), _answer([{**result, "keyword": "session replay", "items": []}])],
        )

        # The SERP endpoint takes one keyword per request and has no limit/offset pagination.
        assert [(request.url, request.json()[0]) for request in driven.requests] == [
            (
                f"{DATAFORSEO_BASE_URL}/serp/google/organic/live/advanced",
                {"keyword": keyword, "location_name": "United States", "language_name": "English"},
            )
            for keyword in ["posthog", "session replay"]
        ]
        assert driven.items == [
            [
                {
                    "type": "organic",
                    "rank_absolute": 1,
                    "domain": "posthog.com",
                    "keyword": "posthog",
                    "se_domain": "google.com",
                    "location_code": 2840,
                    "language_code": "en",
                    "check_url": "https://www.google.com/search?q=posthog",
                    "datetime": "2024-08-11 13:24:34 +00:00",
                }
            ]
        ]

    def test_lookup_endpoint_ignores_saved_resume_state(self) -> None:
        # A lookup has no cursor, so state left behind by another endpoint must not skip the call.
        result = _driver(targets="a.com").run(
            "categories",
            [_answer([{"category_code": 1}])],
            resume_state=DataForSEOResumeConfig(target="a.com", offset=PAGE_SIZE),
        )

        assert len(result.requests) == 1
        assert result.items == [[{"category_code": 1}]]


class TestDataForSEOSourceResponse:
    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver(keywords="posthog").run(endpoint, [_answer([])])
        response = result.response

        config = DATAFORSEO_ENDPOINTS[endpoint]
        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("endpoint", TARGETED_ENDPOINTS)
    def test_targeted_primary_keys_include_target(self, endpoint: str) -> None:
        # A targeted endpoint fans out over the configured targets, so the injected target must
        # be part of the key for table-wide uniqueness.
        assert "target" in DATAFORSEO_ENDPOINTS[endpoint].primary_keys

    @pytest.mark.parametrize("endpoint", KEYWORD_ENDPOINTS)
    def test_keyword_primary_keys_include_keyword(self, endpoint: str) -> None:
        # A keyword-scoped endpoint aggregates rows from every configured keyword, so the keyword
        # must be part of the key for table-wide uniqueness.
        assert "keyword" in DATAFORSEO_ENDPOINTS[endpoint].primary_keys

    @pytest.mark.parametrize("endpoint", UNTARGETED_ENDPOINTS)
    def test_untargeted_primary_keys_exclude_target(self, endpoint: str) -> None:
        # Lookup and keyword-scoped rows carry no target column, so keying on one would key
        # every row on null.
        assert "target" not in DATAFORSEO_ENDPOINTS[endpoint].primary_keys


class TestValidateCredentials:
    def test_unauthorized_is_invalid(self) -> None:
        with scripted_network([ScriptedResponse(status=401, json={})]) as network:
            assert validate_credentials("login", "password") is False
        assert network.requests_log[0].path == "/v3/appendix/user_data"

    def test_error_body_is_invalid(self) -> None:
        with scripted_network([ScriptedResponse(json={"status_code": 40100, "status_message": "unauthorized"})]):
            assert validate_credentials("login", "password") is False

    @pytest.mark.parametrize(("login", "password"), [("", "password"), ("login", ""), (" ", " ")])
    def test_blank_credentials_are_invalid_without_a_request(self, login: str, password: str) -> None:
        assert validate_credentials(login, password) is False
