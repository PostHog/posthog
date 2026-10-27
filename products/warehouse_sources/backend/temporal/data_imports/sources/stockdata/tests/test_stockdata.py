from datetime import date, datetime
from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.stockdata import (
    StockDataSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stockdata.source import StockDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.stockdata.stockdata import (
    StockDataResumeConfig,
    _format_date,
    _format_datetime,
    validate_credentials,
)


def _news_page(data: list[dict[str, Any]], *, found: int, limit: int, page: int) -> ScriptedResponse:
    return _response({"meta": {"found": found, "returned": len(data), "limit": limit, "page": page}, "data": data})


def _data_page(data: Any, *, drop_data: bool = False) -> ScriptedResponse:
    body: dict[str, Any] = {"meta": {}}
    if not drop_data:
        body["data"] = data
    return _response(body)


def _response(body: Any, *, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


def _driver(symbols: str | None = None) -> SourceDriver:
    return SourceDriver(StockDataSource(), StockDataSourceConfig(api_token="supersecret", symbols=symbols))


class TestCursorFormatting:
    @parameterized.expand(
        [
            ("datetime", datetime(2021, 4, 9, 12, 30), "2021-04-09"),
            ("date", date(2021, 4, 9), "2021-04-09"),
            ("iso_string", "2021-04-09T00:00:00+0000", "2021-04-09"),
        ]
    )
    def test_format_date(self, _name: str, value: Any, expected: str) -> None:
        assert _format_date(value) == expected

    @parameterized.expand(
        [
            ("datetime", datetime(2021, 4, 9, 12, 30, 5), "2021-04-09T12:30:05"),
            ("date", date(2021, 4, 9), "2021-04-09"),
            ("iso_string_with_tz", "2021-04-09T12:30:05.123456Z", "2021-04-09T12:30:05"),
        ]
    )
    def test_format_datetime(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestNewsPagination:
    def test_stops_at_20k_result_cap(self) -> None:
        # limit × page can't exceed 20,000; requesting past it errors, so pagination must stop there.
        page1 = [{"uuid": f"u{i}"} for i in range(3)]
        page2 = [{"uuid": f"v{i}"} for i in range(3)]
        result = _driver().run(
            "news",
            [
                _news_page(page1, found=50_000, limit=10_000, page=1),
                _news_page(page2, found=50_000, limit=10_000, page=2),
            ],
        )

        assert len(result.rows) == 6
        assert len(result.requests) == 2

    def test_news_sources_is_not_held_to_the_news_result_cap(self) -> None:
        pages = [[{"source_id": f"p{page}"}] for page in (1, 2, 3)]
        result = _driver().run(
            "news_sources",
            [_news_page(rows, found=30_000, limit=10_000, page=page) for page, rows in enumerate(pages, start=1)],
        )

        assert [request.param("page") for request in result.requests] == ["1", "2", "3"]

    def test_stops_on_empty_first_page(self) -> None:
        result = _driver().run("news", [_news_page([], found=0, limit=100, page=1)])

        assert result.rows == []
        assert len(result.requests) == 1

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "news",
            [_news_page([{"uuid": "u1"}], found=1, limit=100, page=3)],
            resume_state=StockDataResumeConfig(next_page=3),
        )

        # The first request must start from the persisted page, not page 1.
        assert result.requests[0].param("page") == "3"

    @parameterized.expand(
        [
            ("news_sources", "source_id", None),
            ("entity_search", "symbol", "AAPL,MSFT"),
        ]
    )
    def test_metadata_endpoints_walk_every_page(self, endpoint: str, key: str, symbols: str | None) -> None:
        pages = [[{key: f"p{page}-{i}"} for i in range(2)] for page in (1, 2, 3)]
        result = _driver(symbols=symbols).run(
            endpoint,
            [_news_page(rows, found=5, limit=2, page=page) for page, rows in enumerate(pages, start=1)],
        )

        assert [row[key] for row in result.rows] == [row[key] for rows in pages for row in rows]
        assert [request.param("page") for request in result.requests] == ["1", "2", "3"]

    def test_missing_data_key_raises_loudly(self) -> None:
        result = _driver().run("news", [_data_page(None, drop_data=True)])

        # A 200 body without "data" (an error envelope or changed shape) fails loud rather than
        # silently syncing 0 rows.
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestRequestParams:
    def test_news_incremental_passes_published_after_watermark(self) -> None:
        result = _driver().run(
            "news",
            [_news_page([{"uuid": "u1"}], found=1, limit=100, page=1)],
            incremental_field="published_at",
            db_incremental_field_last_value=datetime(2021, 4, 9, 12, 30, 5),
        )

        assert result.requests[0].param("published_after") == "2021-04-09T12:30:05"

    @parameterized.expand(
        [
            ("incremental", datetime(2026, 10, 1), "2026-10-01T00:00:00"),
            ("full_refresh", None, None),
        ]
    )
    def test_news_stats_intraday_requests_ascending_daily_buckets(
        self, _name: str, watermark: datetime | None, expected_published_after: str | None
    ) -> None:
        result = _driver(symbols="tsla, amzn").run(
            "news_stats_intraday",
            [_data_page([])],
            incremental_field="date" if watermark else None,
            db_incremental_field_last_value=watermark,
        )

        request = result.requests[0]
        assert request.param("interval") == "day"
        assert request.param("group_by") == "symbol"
        assert request.param("date_order") == "asc"
        assert request.param("symbols") == "TSLA,AMZN"
        assert request.param("published_after") == expected_published_after

    @parameterized.expand(
        [
            ("news_stats_aggregation_without_symbols", "news_stats_aggregation", None, None),
            ("news_stats_aggregation_with_symbols", "news_stats_aggregation", "TSLA", "TSLA"),
            ("news_sources_ignores_symbols", "news_sources", "TSLA", None),
        ]
    )
    def test_optional_symbols_filter(
        self, _name: str, endpoint: str, symbols: str | None, expected_symbols: str | None
    ) -> None:
        result = _driver(symbols=symbols).run(endpoint, [_news_page([], found=0, limit=50, page=1)])

        assert result.raised is None
        assert result.requests[0].param("symbols") == expected_symbols

    def test_eod_requests_ascending_day_interval_with_date_from_watermark(self) -> None:
        result = _driver(symbols="AAPL").run(
            "eod",
            [_data_page([{"ticker": "AAPL", "date": "2021-04-09", "data": {}}])],
            incremental_field="date",
            db_incremental_field_last_value="2021-04-09T00:00:00+0000",
        )

        request = result.requests[0]
        assert request.param("sort") == "asc"
        assert request.param("interval") == "day"
        assert request.param("symbols") == "AAPL"
        assert request.param("date_from") == "2021-04-09"


class TestNewsStatsRowShaping:
    @parameterized.expand(
        [
            (
                "one_row_per_key_with_bucket_date",
                [
                    {
                        "date": "2026-10-02T00:00:00.000Z",
                        "data": [
                            {"key": "TSLA", "total_documents": 4, "sentiment_avg": 0.25},
                            {"key": "AMZN", "total_documents": 2, "sentiment_avg": -0.5},
                        ],
                    },
                    {
                        "date": "2026-10-01T00:00:00.000Z",
                        "data": [{"key": "TSLA", "total_documents": 1, "sentiment_avg": 0.0}],
                    },
                ],
                [
                    {"date": "2026-10-02T00:00:00.000Z", "key": "TSLA", "total_documents": 4, "sentiment_avg": 0.25},
                    {"date": "2026-10-02T00:00:00.000Z", "key": "AMZN", "total_documents": 2, "sentiment_avg": -0.5},
                    {"date": "2026-10-01T00:00:00.000Z", "key": "TSLA", "total_documents": 1, "sentiment_avg": 0.0},
                ],
            ),
            ("empty_bucket_yields_nothing", [{"date": "2026-10-02T00:00:00.000Z", "data": []}], []),
            ("empty_object_result", {}, []),
        ]
    )
    def test_intraday_buckets_explode_into_rows(
        self, _name: str, data: Any, expected_rows: list[dict[str, Any]]
    ) -> None:
        result = _driver().run("news_stats_intraday", [_data_page(data)])

        assert result.raised is None
        assert result.rows == expected_rows

    @parameterized.expand(
        [
            ("missing_data", {"date": "2026-10-03T00:00:00.000Z"}),
            ("non_list_data", {"date": "2026-10-03T00:00:00.000Z", "data": None}),
            ("non_dict_entry", {"date": "2026-10-04T00:00:00.000Z", "data": ["not-a-dict"]}),
        ]
    )
    def test_malformed_bucket_fails_the_sync(self, _name: str, bucket: dict[str, Any]) -> None:
        valid = {"date": "2026-10-05T00:00:00.000Z", "data": [{"key": "TSLA", "total_documents": 1}]}
        result = _driver().run("news_stats_intraday", [_data_page([bucket, valid])])

        # Dropping the bucket would let the later one advance the watermark past its date.
        assert isinstance(result.raised, ValueError)
        assert "malformed news stats bucket" in str(result.raised)

    def test_aggregation_rows_pass_through_unchanged(self) -> None:
        rows = [{"key": "TSLA", "total_documents": 55, "sentiment_avg": 0.33}]
        result = _driver().run("news_stats_aggregation", [_data_page(rows)])

        assert result.rows == rows


class TestRequiresSymbols:
    @parameterized.expand([("quote",), ("eod",), ("intraday",), ("dividends",), ("splits",), ("entity_search",)])
    def test_price_endpoints_require_symbols(self, endpoint: str) -> None:
        # Selecting a price table with no symbols is a permanent misconfiguration.
        result = _driver(symbols=None).run(endpoint, [])
        assert isinstance(result.raised, ValueError)
        assert "[missing_symbols]" in str(result.raised)

    def test_blank_symbols_treated_as_missing(self) -> None:
        result = _driver(symbols=" , ").run("eod", [])
        assert isinstance(result.raised, ValueError)
        assert "[missing_symbols]" in str(result.raised)


class TestHttpErrors:
    @parameterized.expand(
        [
            ("unauthorized", 401),
            ("payment_required", 402),
            ("forbidden", 403),
        ]
    )
    def test_permanent_status_raises_without_leaking_token(self, _name: str, status: int) -> None:
        result = _driver().run("news", [_response({"error": {"code": "x"}}, status=status)])

        assert isinstance(result.raised, requests.HTTPError)
        # The api_token rides in the query string, so it must be redacted out of the error message
        # that becomes the user-visible `latest_error`.
        assert str(status) in str(result.raised)
        assert "supersecret" not in str(result.raised)
        # Permanent credential/plan/quota problem — not retried.
        assert len(result.requests) == 1


class TestSourceResponse:
    @parameterized.expand(
        [
            ("news", ["uuid"], "published_at", "desc"),
            ("quote", ["ticker"], None, "asc"),
            ("eod", ["ticker", "date"], "date", "asc"),
            ("intraday", ["ticker", "date"], "date", "asc"),
            ("dividends", ["ticker", "date"], "date", "asc"),
            ("splits", ["ticker", "date"], "date", "asc"),
            ("entity_search", ["symbol"], None, "asc"),
            ("news_sources", ["source_id"], None, "asc"),
            ("news_stats_intraday", ["date", "key"], "date", "asc"),
            ("news_stats_aggregation", ["key"], None, "asc"),
        ]
    )
    def test_source_response_keys_partitioning_and_sort(
        self, endpoint: str, expected_keys: list[str], expected_partition: str | None, expected_sort: str
    ) -> None:
        response = _driver(symbols="AAPL").run(endpoint, []).response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == expected_sort
        if expected_partition is None:
            assert response.partition_keys is None
        else:
            assert response.partition_keys == [expected_partition]
            assert response.partition_mode == "datetime"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("quota_exhausted_token_still_genuine", 402, True),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            ok, message = validate_credentials("k")
        assert ok is expected
        if expected:
            assert message is None
        else:
            assert message
