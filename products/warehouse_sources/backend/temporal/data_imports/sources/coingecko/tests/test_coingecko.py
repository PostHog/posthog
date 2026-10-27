import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal, cast

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.coingecko import (
    DEMO_BASE_URL,
    NO_COINS_ERROR,
    PLAN_DEMO,
    PLAN_PRO,
    PRO_BASE_URL,
    CoinGeckoResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.settings import (
    CHART_WINDOW_DAYS,
    DEFAULT_HISTORY_DAYS,
    MAX_COINS,
    TICKERS_PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.source import CoinGeckoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coingecko import (
    CoinGeckoSourceConfig,
)


def _driver(
    plan: str = PLAN_DEMO,
    api_key: str = "key",
    coin_ids: str | None = None,
    start_date: str | None = None,
) -> SourceDriver:
    return SourceDriver(
        CoinGeckoSource(),
        CoinGeckoSourceConfig(
            plan=cast(Literal["demo", "pro"], plan), api_key=api_key, coin_ids=coin_ids, start_date=start_date
        ),
    )


def _today() -> date:
    return datetime.now(UTC).date()


class TestReferenceEndpoints:
    def test_non_list_body_fails_loud(self) -> None:
        # A 200 that isn't a bare array is an unexpected/changed shape — fail loud, not a garbage row.
        result = _driver().run("coins_list", [ScriptedResponse(json={"unexpected": "object"})])

        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)

    def test_reference_endpoint_never_checkpoints(self) -> None:
        result = _driver().run("asset_platforms", [ScriptedResponse(json=[{"id": "eth"}])])

        assert result.rows == [{"id": "eth"}]
        assert result.saved_states == []


class TestPagination:
    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "coins_markets",
            [ScriptedResponse(json=[{"id": "x"}])],
            resume_state=CoinGeckoResumeConfig(page=3),
        )

        assert result.rows == [{"id": "x"}]
        assert result.params("page") == ["3"]

    def test_insights_stops_at_max_page_cap(self) -> None:
        # 20 full pages back to back would normally trigger a 21st request, but CoinGecko rejects
        # page > 20 for /insights, so the cap must stop paging without that doomed request.
        full_page = [{"title": f"t{i}", "posted_at": "2026-01-01T00:00:00Z"} for i in range(20)]
        result = _driver(plan=PLAN_PRO).run("insights", [ScriptedResponse(json=full_page) for _ in range(20)])

        assert result.raised is None
        assert len(result.requests) == 20
        assert result.params("page") == [str(page) for page in range(1, 21)]


class TestRateLimitAndErrors:
    @parameterized.expand([("compact", True), ("spaced", False)])
    def test_in_body_rate_limit_is_retried(self, _name: str, compact: bool) -> None:
        good = [{"id": "btc"}]
        # A 200 body carrying the rate-limit envelope must be retried, then the retry succeeds —
        # regardless of the server's JSON whitespace.
        body = {"status": {"error_code": 429, "error_message": "rate limited"}}
        separators = (",", ":") if compact else None
        result = _driver().run(
            "coins_list",
            [ScriptedResponse(body=json.dumps(body, separators=separators).encode()), ScriptedResponse(json=good)],
        )

        assert result.raised is None
        assert result.rows == good
        assert len(result.requests) == 2

    def test_401_surfaces_as_http_error(self) -> None:
        # 401 is a genuine, non-retryable auth error — it must surface (get_non_retryable_errors
        # matches on the "401 ... for url: <host>" message).
        body = {"status": {"error_code": 10011, "error_message": "invalid key"}}
        result = _driver().run("coins_list", [ScriptedResponse(status=401, json=body)])

        assert isinstance(result.raised, requests.HTTPError)
        assert "401" in str(result.raised)
        assert len(result.requests) == 1


class TestHostHeaderAndRedaction:
    @parameterized.expand(
        [
            (PLAN_DEMO, DEMO_BASE_URL, "x-cg-demo-api-key"),
            (PLAN_PRO, PRO_BASE_URL, "x-cg-pro-api-key"),
        ]
    )
    def test_plan_selects_host_and_key_header(self, plan: str, base_url: str, header_name: str) -> None:
        result = _driver(plan=plan, api_key="secret").run("coins_list", [ScriptedResponse(json=[{"id": "btc"}])])

        assert result.raised is None
        assert result.urls[0].startswith(base_url)
        # The key rides in the plan-specific header via framework auth (redacted by value).
        assert result.requests[0].headers[header_name] == "secret"

    def test_api_key_registered_for_redaction(self) -> None:
        result = _driver(api_key="secret").run("coins_list", [ScriptedResponse(json=[{"id": "btc"}])])

        # RESTClient builds its tracked session with the auth secret in redact_values.
        assert result.session_options[0]["redact_values"] == ("secret",)


class TestValidateCredentials:
    def test_pings_plan_host_with_key_and_redaction(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            assert validate_credentials(PLAN_PRO, "secret") is True

        assert network.requests_log[0].url == f"{PRO_BASE_URL}/ping"
        assert network.requests_log[0].headers["x-cg-pro-api-key"] == "secret"
        assert network.session_options[0]["redact_values"] == ("secret",)


class TestSourceResponse:
    @parameterized.expand(
        [
            ("coins_list", ["id"]),
            ("coins_markets", ["id"]),
            ("coins_categories", ["id"]),
            ("coins_categories_list", ["category_id"]),
            ("exchanges", ["id"]),
            ("exchanges_list", ["id"]),
            ("asset_platforms", ["id"]),
            ("rwas_markets", ["id"]),
            ("rwas_list", ["id"]),
            ("rwas_issuers_list", ["id"]),
        ]
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_keys: list[str]) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == expected_keys


class TestCoinTickers:
    def test_pages_one_coin_then_moves_to_the_next(self) -> None:
        full_page = [
            {"base": f"B{i}", "target": "USDT", "market": {"identifier": "binance"}} for i in range(TICKERS_PAGE_SIZE)
        ]
        result = _driver(coin_ids="bitcoin,ethereum").run(
            "coins_tickers",
            [
                ScriptedResponse(json={"name": "Bitcoin", "tickers": full_page}),
                ScriptedResponse(
                    json={
                        "name": "Bitcoin",
                        "tickers": [{"base": "last", "target": "USDT", "market": {"identifier": "binance"}}],
                    }
                ),
                ScriptedResponse(
                    json={
                        "name": "Ethereum",
                        "tickers": [{"base": "ETH", "target": "USDT", "market": {"identifier": "kraken"}}],
                    }
                ),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == TICKERS_PAGE_SIZE + 2
        assert result.params("page") == ["1", "2", "1"]
        # The endpoint has no per_page parameter, so sending one would be rejected.
        assert result.params("per_page") == [None, None, None]
        assert result.saved_states == [
            CoinGeckoResumeConfig(page=2, coin_index=0),
            CoinGeckoResumeConfig(coin_index=1),
            CoinGeckoResumeConfig(coin_index=2),
        ]

    @parameterized.expand([("blank", ""), ("unset", None), ("separators only", " , ")])
    def test_no_coins_fails_with_the_curated_error(self, _name: str, coin_ids: str | None) -> None:
        result = _driver(coin_ids=coin_ids).run("coins_tickers", [])

        assert isinstance(result.raised, ValueError)
        assert NO_COINS_ERROR in str(result.raised)

    def test_coin_list_is_capped(self) -> None:
        # A stored configuration can carry more coins than the cap, and each one costs a request.
        coin_ids = ",".join(f"coin-{i}" for i in range(MAX_COINS + 5))
        result = _driver(coin_ids=coin_ids).run(
            "coins_tickers", [ScriptedResponse(json={"name": "c", "tickers": []}) for _ in range(MAX_COINS + 5)]
        )

        assert result.raised is None
        assert len(result.requests) == MAX_COINS


class TestMarketChart:
    def test_series_of_unequal_length_still_line_up(self) -> None:
        first, second = 1764547200000, 1764633600000
        # CoinGecko can return a volume point the price series has not caught up with yet.
        start = (_today() - timedelta(days=5)).isoformat()
        result = _driver(plan=PLAN_PRO, coin_ids="bitcoin", start_date=start).run(
            "coins_market_chart",
            [ScriptedResponse(json={"prices": [[first, 1.0]], "market_caps": [], "total_volumes": [[second, 2.0]]})],
        )

        assert result.raised is None
        assert [sorted(row.keys()) for row in result.rows] == [
            ["coin_id", "price", "timestamp"],
            ["coin_id", "timestamp", "total_volume"],
        ]

    def test_non_object_body_fails_loud(self) -> None:
        start = (_today() - timedelta(days=5)).isoformat()
        result = _driver(plan=PLAN_PRO, coin_ids="bitcoin", start_date=start).run(
            "coins_market_chart", [ScriptedResponse(json="unexpected")]
        )

        assert isinstance(result.raised, ValueError)
        assert "market chart object" in str(result.raised)


class TestOhlc:
    @parameterized.expand(
        [("short candle", [[1764547200000, 1.0, 2.0]]), ("unparseable timestamp", [["nope", 1.0, 2.0, 3.0, 4.0]])]
    )
    def test_unusable_candles_are_dropped(self, _name: str, body: list[Any]) -> None:
        start = (_today() - timedelta(days=5)).isoformat()
        result = _driver(plan=PLAN_PRO, coin_ids="bitcoin", start_date=start).run(
            "coins_ohlc", [ScriptedResponse(json=body)]
        )

        assert result.raised is None
        assert result.rows == []


class TestChartWindows:
    def test_one_batch_holds_every_coin_for_a_window(self) -> None:
        today = _today()
        start = today - timedelta(days=CHART_WINDOW_DAYS + 10)
        first_candle, second_candle = 1764547200000, 1764633600000
        result = _driver(plan=PLAN_PRO, coin_ids="bitcoin,ethereum", start_date=start.isoformat()).run(
            "coins_ohlc",
            [
                ScriptedResponse(json=[[first_candle, 1.0, 2.0, 3.0, 4.0]]),
                ScriptedResponse(json=[[first_candle, 5.0, 6.0, 7.0, 8.0]]),
                ScriptedResponse(json=[[second_candle, 1.0, 2.0, 3.0, 4.0]]),
                ScriptedResponse(json=[[second_candle, 5.0, 6.0, 7.0, 8.0]]),
            ],
        )

        # The pipeline commits the incremental watermark to the highest timestamp in each batch, so
        # a batch carrying one coin past a window the other has not been fetched for would let the
        # next job start beyond the coin left behind and skip it for good.
        assert result.raised is None
        assert [[row["coin_id"] for row in batch] for batch in result.items] == [
            ["bitcoin", "ethereum"],
            ["bitcoin", "ethereum"],
        ]
        # Both coins are fetched for one window before either moves on to the next.
        windows = result.params("from")
        assert windows[0] == windows[1] and windows[2] == windows[3] and windows[0] != windows[2]
        assert result.saved_states[-1] == CoinGeckoResumeConfig(next_start=(today + timedelta(days=1)).isoformat())

    def test_full_refresh_starts_at_the_default_history_window(self) -> None:
        # No configured start date and no watermark: the first window must start at the furthest
        # back every plan serves, not at the API's own earliest data.
        result = _driver(plan=PLAN_PRO, coin_ids="bitcoin").run(
            "coins_ohlc", [ScriptedResponse(json=[]) for _ in range(4)], db_incremental_field_last_value="2020-01-01"
        )

        assert result.raised is None
        assert result.params("from")[0] == (_today() - timedelta(days=DEFAULT_HISTORY_DAYS)).isoformat()

    def test_incremental_starts_at_the_last_synced_day(self) -> None:
        # Relative to today, so the number of windows between the watermark and now stays fixed
        # however far the real clock moves past this test.
        last_synced_day = _today() - timedelta(days=10)
        result = _driver(
            plan=PLAN_PRO, coin_ids="bitcoin", start_date=(last_synced_day - timedelta(days=400)).isoformat()
        ).run(
            "coins_ohlc",
            [ScriptedResponse(json=[]) for _ in range(4)],
            incremental_field="timestamp",
            db_incremental_field_last_value=datetime.combine(last_synced_day, time(9, 30), tzinfo=UTC),
        )

        # Re-reads the last synced day rather than starting after it: that day was still moving
        # when it first landed, and merge dedupes the overlap.
        assert result.raised is None
        assert result.params("from")[0] == last_synced_day.isoformat()

    def test_resumes_at_the_saved_window(self) -> None:
        resumed_from = (_today() - timedelta(days=3)).isoformat()
        result = _driver(
            plan=PLAN_PRO, coin_ids="bitcoin,ethereum", start_date=(_today() - timedelta(days=300)).isoformat()
        ).run(
            "coins_ohlc",
            [ScriptedResponse(json=[]) for _ in range(4)],
            resume_state=CoinGeckoResumeConfig(next_start=resumed_from),
        )

        # The saved window is re-fetched for every coin, so resuming cannot drop one of them.
        assert result.raised is None
        assert len(result.requests) == 2
        assert result.params("from") == [resumed_from, resumed_from]
        assert result.paths == ["/api/v3/coins/bitcoin/ohlc/range", "/api/v3/coins/ethereum/ohlc/range"]


class TestExchangeRates:
    def test_flattens_the_rates_object_into_a_row_per_currency(self) -> None:
        # The body is keyed by currency code rather than being a row list, so without the flattening
        # the whole object would land as one unusable row.
        result = _driver().run(
            "exchange_rates",
            [
                ScriptedResponse(
                    json={
                        "rates": {
                            "btc": {"name": "Bitcoin", "unit": "BTC", "value": 1.0, "type": "crypto"},
                            "usd": {"name": "US Dollar", "unit": "$", "value": 80443.4, "type": "fiat"},
                        }
                    }
                )
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"id": "btc", "name": "Bitcoin", "unit": "BTC", "value": 1.0, "type": "crypto"},
            {"id": "usd", "name": "US Dollar", "unit": "$", "value": 80443.4, "type": "fiat"},
        ]
        assert len(result.requests) == 1


class TestGlobalMarketCapChart:
    @parameterized.expand(
        [
            # The endpoint takes a relative window from a fixed enum, so a gap picks the smallest
            # option that still covers it. A gap of one day still asks for 7: `days=1` is served
            # hourly and would not line up with the daily rows already synced.
            ("one day behind", 1, "7"),
            ("a week behind", 7, "14"),
            ("a month behind", 40, "90"),
            ("beyond the largest window", 400, "max"),
        ]
    )
    def test_incremental_narrows_the_window_to_the_watermark(
        self, _name: str, days_behind: int, expected_days: str
    ) -> None:
        result = _driver(plan=PLAN_PRO).run(
            "global_market_cap_chart",
            [ScriptedResponse(json={"market_cap_chart": {"market_cap": [], "volume": []}})],
            incremental_field="timestamp",
            db_incremental_field_last_value=datetime.combine(
                _today() - timedelta(days=days_behind), time(9, 30), tzinfo=UTC
            ),
        )

        assert result.raised is None
        assert result.params("days") == [expected_days]


class TestReshapedEndpointsFailLoud:
    @parameterized.expand(
        [
            ("exchange rates, no envelope", "exchange_rates", {"unexpected": "object"}, "data_selector"),
            ("exchange rates, wrong inner type", "exchange_rates", {"rates": []}, "exchange rates object"),
            ("global chart, no envelope", "global_market_cap_chart", {"unexpected": "object"}, "data_selector"),
            (
                "global chart, wrong inner type",
                "global_market_cap_chart",
                {"market_cap_chart": []},
                "global market cap chart object",
            ),
        ]
    )
    def test_unexpected_shape_fails_loud(self, _name: str, endpoint: str, body: Any, expected_message: str) -> None:
        # These bodies are reshaped rather than yielded as rows, so a changed shape must fail rather
        # than silently syncing zero rows or one garbage row.
        result = _driver(plan=PLAN_PRO).run(endpoint, [ScriptedResponse(json=body)])

        assert isinstance(result.raised, ValueError)
        assert expected_message in str(result.raised)
