from datetime import UTC, date, datetime
from typing import Any

import time_machine

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.newsdata import (
    NewsDataSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.newsdata.newsdata import (
    NewsDataResumeConfig,
    _to_from_date,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.newsdata.source import NewsDataSource


def _driver() -> SourceDriver:
    return SourceDriver(NewsDataSource(), NewsDataSourceConfig(api_key="pub_test"))


def _page(results: list[dict[str, Any]], next_page: str | None) -> ScriptedResponse:
    return ScriptedResponse(json={"status": "success", "results": results, "nextPage": next_page})


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


class TestPagination:
    def test_follows_next_page_until_absent(self) -> None:
        result = _driver().run(
            "latest",
            [_page([{"article_id": "a1"}], "p2"), _page([{"article_id": "a2"}], None)],
        )

        assert result.raised is None
        assert [row["article_id"] for row in result.rows] == ["a1", "a2"]
        assert len(result.requests) == 2
        # The opaque `nextPage` cursor is echoed back as the `page` query param on the next request.
        assert result.params("page") == [None, "p2"]
        # The key rides on framework api_key auth (X-ACCESS-KEY header), never a query param.
        assert result.requests[0].headers["x-access-key"] == "pub_test"
        assert result.params("apikey") == [None, None]

    def test_sources_endpoint_never_paginates(self) -> None:
        # /sources rejects the `page` param, so even a stray nextPage in the body must not trigger a
        # second request.
        result = _driver().run("sources", [_page([{"id": "bbc"}], "ignored")])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["bbc"]
        assert result.paths == ["/api/1/sources"]
        assert result.params("page") == [None]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "latest",
            [_page([{"article_id": "a3"}], None)],
            resume_state=NewsDataResumeConfig(next_page="saved_cursor"),
        )

        assert result.raised is None
        assert [row["article_id"] for row in result.rows] == ["a3"]
        # The saved cursor seeds the very first request.
        assert result.params("page") == ["saved_cursor"]


class TestIncrementalFromDate:
    @parameterized.expand(
        [
            # /latest and /sources reject from_date entirely, so it must never be sent even when the
            # sync is incremental — doing so 4xxs the whole run.
            ("latest_incremental", "latest", True, datetime(2024, 1, 15, tzinfo=UTC)),
            ("sources_incremental", "sources", True, datetime(2024, 1, 15, tzinfo=UTC)),
            # A date-filter endpoint syncing full-refresh sends no window either.
            ("archive_full_refresh", "archive", False, datetime(2024, 1, 15, tzinfo=UTC)),
        ]
    )
    def test_no_from_date(self, _name: str, endpoint: str, incremental: bool, watermark: Any) -> None:
        result = _driver().run(
            endpoint,
            [_page([{"article_id": "x"}], None)],
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        assert result.params("from_date") == [None]

    @parameterized.expand([("archive",), ("crypto",), ("market",)])
    def test_incremental_uses_watermark_date(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [_page([{"article_id": "x"}], None)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.paths == [f"/api/1/{endpoint}"]
        assert result.params("from_date") == ["2024-03-04"]

    @parameterized.expand([("archive",), ("crypto",), ("market",)])
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_first_sync_applies_lookback_floor(self, endpoint: str) -> None:
        # Without a watermark the first sync must floor at the trailing lookback window instead of
        # crawling the entire (up to 7-year) archive.
        result = _driver().run(
            endpoint,
            [_page([{"article_id": "x"}], None)],
            should_use_incremental_field=True,
        )

        assert result.raised is None
        assert result.params("from_date") == ["2026-05-16"]


class TestErrorBody:
    def test_status_error_body_raises(self) -> None:
        # NewsData reports hard failures (unsupported param, quota exhausted) in a 200-body envelope;
        # fail loud instead of silently syncing 0 rows.
        result = _driver().run(
            "latest",
            [
                ScriptedResponse(
                    body=b'{"status":"error","results":{"message":"quota exceeded","code":"TooManyRequests"}}'
                )
            ],
        )

        assert isinstance(result.raised, ValueError)


class TestRetries:
    @parameterized.expand([("rate_limited", 429, "Too Many Requests"), ("server_error", 503, "Service Unavailable")])
    def test_retryable_status_retries_then_raises(self, _name: str, status: int, reason: str) -> None:
        result = _driver().run("latest", always(ScriptedResponse(status=status, json={})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert f"HTTP {status}" in str(result.raised)
        assert len(result.requests) == 5

    @parameterized.expand([("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden")])
    def test_client_error_raises_http_error_without_retry(self, _name: str, status: int, reason: str) -> None:
        # 401/403 are credential/permission failures — never retried, surfaced as an HTTPError whose
        # message carries the stable status text that get_non_retryable_errors matches on.
        result = _driver().run("latest", [ScriptedResponse(status=status, json={"status": "error"})])

        assert isinstance(result.raised, requests.HTTPError)
        assert f"{status} Client Error" in str(result.raised)
        assert reason in str(result.raised)
        assert "https://newsdata.io" in str(result.raised)
        assert len(result.requests) == 1


class TestSourceResponseMetadata:
    @parameterized.expand(
        [
            ("latest", ["article_id"], "pubDate", "asc"),
            ("archive", ["article_id"], "pubDate", "desc"),
            ("crypto", ["article_id"], "pubDate", "desc"),
            ("market", ["article_id"], "pubDate", "desc"),
        ]
    )
    def test_partitioned_endpoints(
        self, endpoint: str, primary_keys: list[str], partition_key: str, sort_mode: str
    ) -> None:
        result = _driver().run(endpoint, [_page([], None)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == primary_keys
        assert result.response.sort_mode == sort_mode
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == [partition_key]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_maps_to_bool(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("pub_test") is expected

        assert [request.path for request in network.requests_log] == ["/api/1/sources"]
        assert network.requests_log[0].headers["x-access-key"] == "pub_test"
