import json
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.coingecko import (
    DEMO_BASE_URL,
    NO_COINS_ERROR,
    PAGE_SIZE,
    PLAN_DEMO,
    PLAN_PRO,
    PRO_BASE_URL,
    CoinGeckoResumeConfig,
    coingecko_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.settings import (
    CHART_WINDOW_DAYS,
    COINGECKO_ENDPOINTS,
    DEFAULT_HISTORY_DAYS,
    MAX_COINS,
    TICKERS_PAGE_SIZE,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the coingecko module.
COINGECKO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.coingecko.make_tracked_session"
)
# Neuter tenacity's backoff so retry tests don't actually sleep.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(body: Any, *, status: int = 200, compact: bool = False) -> Response:
    resp = Response()
    resp.status_code = status
    separators = (",", ":") if compact else None
    resp._content = json.dumps(body, separators=separators).encode()
    resp.url = "https://api.coingecko.com/api/v3/x"
    return resp


def _rate_limit_body(*, compact: bool) -> Response:
    # CoinGecko's keyless/demo tier reports rate limiting inside a 200 body.
    return _response({"status": {"error_code": 429, "error_message": "rate limited"}}, compact=compact)


def _manager(resume_state: CoinGeckoResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's URL/params/auth AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy per request.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        auth = request.auth
        snapshots.append(
            {
                "url": request.url,
                "params": dict(request.params or {}),
                "auth_name": getattr(auth, "name", None),
                "auth_key": getattr(auth, "api_key", None),
            }
        )
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(
    plan: str,
    api_key: str,
    endpoint: str,
    manager: mock.MagicMock,
    coin_ids: str | None = None,
    start_date: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
):
    return coingecko_source(
        plan=plan,
        api_key=api_key,
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        logger=mock.MagicMock(),
        resumable_source_manager=manager,
        coin_ids=coin_ids,
        start_date=start_date,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


def _today() -> Any:
    return datetime.now(UTC).date()


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestReferenceEndpoints:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_request_yields_rows(self, MockSession) -> None:
        session = MockSession.return_value
        rows = [{"id": "bitcoin", "symbol": "btc", "name": "Bitcoin"}]
        _wire(session, [_response(rows)])

        assert _rows(_source(PLAN_DEMO, "key", "coins_list", _manager())) == rows
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_body_yields_nothing_and_no_extra_request(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        assert _rows(_source(PLAN_DEMO, "key", "coins_list", _manager())) == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_fails_loud(self, MockSession) -> None:
        session = MockSession.return_value
        # A 200 that isn't a bare array is an unexpected/changed shape — fail loud, not a garbage row.
        _wire(session, [_response({"unexpected": "object"})])

        with pytest.raises(ValueError, match="list response body"):
            _rows(_source(PLAN_DEMO, "key", "coins_list", _manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reference_endpoint_never_checkpoints(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "eth"}])])

        manager = _manager()
        _rows(_source(PLAN_DEMO, "key", "asset_platforms", manager))
        manager.save_state.assert_not_called()


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_until_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": f"c{i}"} for i in range(PAGE_SIZE)]
        short_page = [{"id": "last"}]
        snaps = _wire(session, [_response(full_page), _response(short_page)])

        manager = _manager()
        rows = _rows(_source(PLAN_DEMO, "key", "coins_markets", manager))

        assert rows == [*full_page, *short_page]
        # Page number progresses 1 -> 2; the short page ends it without a third request.
        assert session.send.call_count == 2
        assert snaps[0]["params"]["page"] == 1
        assert snaps[0]["params"]["per_page"] == PAGE_SIZE
        assert snaps[1]["params"]["page"] == 2
        # Checkpoint saved once after the first full page, pointing at the next page.
        manager.save_state.assert_called_once_with(CoinGeckoResumeConfig(page=2))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_terminates_on_empty_page(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": f"c{i}"} for i in range(PAGE_SIZE)]
        _wire(session, [_response(full_page), _response([])])

        manager = _manager()
        rows = _rows(_source(PLAN_DEMO, "key", "coins_markets", manager))

        assert rows == full_page
        assert session.send.call_count == 2
        manager.save_state.assert_called_once_with(CoinGeckoResumeConfig(page=2))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "a"}, {"id": "b"}])])

        manager = _manager()
        rows = _rows(_source(PLAN_DEMO, "key", "coins_markets", manager))

        assert [r["id"] for r in rows] == ["a", "b"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response([{"id": "x"}])])

        manager = _manager(CoinGeckoResumeConfig(page=3))
        _rows(_source(PLAN_DEMO, "key", "coins_markets", manager))

        assert snaps[0]["params"]["page"] == 3

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sends_static_extra_params(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response([{"id": "btc"}])])

        _rows(_source(PLAN_DEMO, "key", "coins_markets", _manager()))
        assert snaps[0]["params"]["vs_currency"] == "usd"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_insights_requests_capped_per_page(self, MockSession) -> None:
        session = MockSession.return_value
        # CoinGecko caps /insights per_page at 20, so the source must not send the default 250.
        snaps = _wire(session, [_response([{"title": "t", "posted_at": "2026-01-01T00:00:00Z"}])])

        _rows(_source(PLAN_PRO, "key", "insights", _manager()))
        assert snaps[0]["params"]["per_page"] == 20

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_insights_stops_at_max_page_cap(self, MockSession) -> None:
        session = MockSession.return_value
        # 20 full pages back to back would normally trigger a 21st request, but CoinGecko rejects
        # page > 20 for /insights, so the cap must stop paging without that doomed request.
        full_page = [{"title": f"t{i}", "posted_at": "2026-01-01T00:00:00Z"} for i in range(20)]
        _wire(session, [_response(full_page) for _ in range(20)])

        _rows(_source(PLAN_PRO, "key", "insights", _manager()))
        assert session.send.call_count == 20


class TestRateLimitAndErrors:
    @parameterized.expand([("compact", True), ("spaced", False)])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_in_body_rate_limit_is_retried(self, _name: str, compact: bool, MockSession, _sleep) -> None:
        session = MockSession.return_value
        good = [{"id": "btc"}]
        # A 200 body carrying the rate-limit envelope must be retried, then the retry succeeds —
        # regardless of the server's JSON whitespace.
        _wire(session, [_rate_limit_body(compact=compact), _response(good)])

        rows = _rows(_source(PLAN_DEMO, "key", "coins_list", _manager()))
        assert rows == good
        assert session.send.call_count == 2

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_http_429_status_is_retried(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        good = [{"id": "btc"}]
        _wire(session, [_response({}, status=429), _response(good)])

        rows = _rows(_source(PLAN_DEMO, "key", "coins_list", _manager()))
        assert rows == good
        assert session.send.call_count == 2

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_http_500_status_is_retried(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        good = [{"id": "btc"}]
        _wire(session, [_response({}, status=500), _response(good)])

        rows = _rows(_source(PLAN_DEMO, "key", "coins_list", _manager()))
        assert rows == good
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_401_surfaces_as_http_error(self, MockSession) -> None:
        session = MockSession.return_value
        # 401 is a genuine, non-retryable auth error — it must surface (get_non_retryable_errors
        # matches on the "401 ... for url: <host>" message).
        resp = _response({"status": {"error_code": 10011, "error_message": "invalid key"}}, status=401)
        _wire(session, [resp])

        with pytest.raises(requests.HTTPError, match="401"):
            _rows(_source(PLAN_DEMO, "key", "coins_list", _manager()))
        assert session.send.call_count == 1


class TestHostHeaderAndRedaction:
    @parameterized.expand(
        [
            (PLAN_DEMO, DEMO_BASE_URL, "x-cg-demo-api-key"),
            (PLAN_PRO, PRO_BASE_URL, "x-cg-pro-api-key"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_plan_selects_host_and_key_header(self, plan: str, base_url: str, header_name: str, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response([{"id": "btc"}])])

        _rows(_source(plan, "secret", "coins_list", _manager()))
        assert snaps[0]["url"].startswith(base_url)
        # The key rides in the plan-specific header via framework auth (redacted by value).
        assert snaps[0]["auth_name"] == header_name
        assert snaps[0]["auth_key"] == "secret"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_api_key_registered_for_redaction(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "btc"}])])

        _rows(_source(PLAN_DEMO, "secret", "coins_list", _manager()))
        # RESTClient builds its tracked session with the auth secret in redact_values.
        assert MockSession.call_args.kwargs["redact_values"] == ("secret",)


class TestValidateCredentials:
    @parameterized.expand([("valid", 200, True), ("unauthorized", 401, False)])
    @mock.patch(COINGECKO_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status: int, expected: bool, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials(PLAN_DEMO, "key") is expected

    @mock.patch(COINGECKO_SESSION_PATCH)
    def test_transient_error_returns_false(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials(PLAN_PRO, "key") is False

    @mock.patch(COINGECKO_SESSION_PATCH)
    def test_pings_plan_host_with_key_and_redaction(self, mock_session: mock.MagicMock) -> None:
        get = mock_session.return_value.get
        get.return_value = mock.MagicMock(status_code=200)
        validate_credentials(PLAN_PRO, "secret")

        assert get.call_args.args[0] == f"{PRO_BASE_URL}/ping"
        assert get.call_args.kwargs["headers"]["x-cg-pro-api-key"] == "secret"
        assert mock_session.call_args.kwargs["redact_values"] == ("secret",)


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
        ]
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_keys: list[str]) -> None:
        response = _source(PLAN_DEMO, "key", endpoint, _manager())
        assert response.name == endpoint
        assert response.primary_keys == expected_keys

    def test_every_settings_endpoint_builds_a_source_response(self) -> None:
        for endpoint in COINGECKO_ENDPOINTS:
            response = _source(PLAN_DEMO, "key", endpoint, _manager())
            assert response.name == endpoint
            assert response.primary_keys == COINGECKO_ENDPOINTS[endpoint].primary_keys


class TestGlobalMarketData:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unwraps_the_data_envelope_into_one_row(self, MockSession) -> None:
        session = MockSession.return_value
        # /global is the one endpoint whose rows sit under an envelope key rather than being a bare
        # array, so a missing selector would sync zero rows or fail the shape check.
        totals = {"active_cryptocurrencies": 17397, "markets": 1476, "updated_at": 1779878351}
        _wire(session, [_response({"data": totals})])

        assert _rows(_source(PLAN_DEMO, "key", "global_market_data", _manager())) == [totals]
        assert session.send.call_count == 1


class TestCoinTickers:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_configured_coins(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _response(
                    {
                        "name": "Bitcoin",
                        "tickers": [{"base": "BTC", "target": "USDT", "market": {"identifier": "binance"}}],
                    }
                ),
                _response(
                    {
                        "name": "Ethereum",
                        "tickers": [{"base": "ETH", "target": "USDT", "market": {"identifier": "kraken"}}],
                    }
                ),
            ],
        )

        rows = _rows(_source(PLAN_DEMO, "key", "coins_tickers", _manager(), coin_ids="bitcoin, ethereum"))

        assert [row["coin_id"] for row in rows] == ["bitcoin", "ethereum"]
        # The exchange id is lifted out of the nested `market` object so every part of the primary
        # key is a flat column.
        assert [row["market_identifier"] for row in rows] == ["binance", "kraken"]
        assert snaps[0]["url"].endswith("/coins/bitcoin/tickers")
        assert snaps[1]["url"].endswith("/coins/ethereum/tickers")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_market_identifier_survives_a_missing_market(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"name": "Bitcoin", "tickers": [{"base": "BTC", "target": "USDT"}]})])

        rows = _rows(_source(PLAN_DEMO, "key", "coins_tickers", _manager(), coin_ids="bitcoin"))
        assert rows[0]["market_identifier"] is None

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pages_one_coin_then_moves_to_the_next(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [
            {"base": f"B{i}", "target": "USDT", "market": {"identifier": "binance"}} for i in range(TICKERS_PAGE_SIZE)
        ]
        snaps = _wire(
            session,
            [
                _response({"name": "Bitcoin", "tickers": full_page}),
                _response(
                    {
                        "name": "Bitcoin",
                        "tickers": [{"base": "last", "target": "USDT", "market": {"identifier": "binance"}}],
                    }
                ),
                _response(
                    {
                        "name": "Ethereum",
                        "tickers": [{"base": "ETH", "target": "USDT", "market": {"identifier": "kraken"}}],
                    }
                ),
            ],
        )

        manager = _manager()
        rows = _rows(_source(PLAN_DEMO, "key", "coins_tickers", manager, coin_ids="bitcoin,ethereum"))

        assert len(rows) == TICKERS_PAGE_SIZE + 2
        assert [snap["params"].get("page") for snap in snaps] == [1, 2, 1]
        # The endpoint has no per_page parameter, so sending one would be rejected.
        assert all("per_page" not in snap["params"] for snap in snaps)
        assert manager.save_state.call_args_list == [
            mock.call(CoinGeckoResumeConfig(page=2, coin_index=0)),
            mock.call(CoinGeckoResumeConfig(coin_index=1)),
            mock.call(CoinGeckoResumeConfig(coin_index=2)),
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_at_the_saved_coin_and_page(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response({"name": "Solana", "tickers": [{"base": "SOL", "target": "USDT"}]})])

        manager = _manager(CoinGeckoResumeConfig(page=4, coin_index=2))
        rows = _rows(_source(PLAN_DEMO, "key", "coins_tickers", manager, coin_ids="bitcoin,ethereum,solana"))

        assert session.send.call_count == 1
        assert snaps[0]["url"].endswith("/coins/solana/tickers")
        assert snaps[0]["params"]["page"] == 4
        assert [row["coin_id"] for row in rows] == ["solana"]

    @parameterized.expand([("blank", ""), ("unset", None), ("separators only", " , ")])
    def test_no_coins_fails_with_the_curated_error(self, _name: str, coin_ids: str | None) -> None:
        with pytest.raises(ValueError, match=NO_COINS_ERROR):
            _rows(_source(PLAN_DEMO, "key", "coins_tickers", _manager(), coin_ids=coin_ids))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_coin_list_is_capped(self, MockSession) -> None:
        session = MockSession.return_value
        # A stored configuration can carry more coins than the cap, and each one costs a request.
        _wire(session, [_response({"name": "c", "tickers": []}) for _ in range(MAX_COINS + 5)])

        coin_ids = ",".join(f"coin-{i}" for i in range(MAX_COINS + 5))
        _rows(_source(PLAN_DEMO, "key", "coins_tickers", _manager(), coin_ids=coin_ids))
        assert session.send.call_count == MAX_COINS

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_duplicate_coins_are_fetched_once(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"name": "Bitcoin", "tickers": []})])

        _rows(_source(PLAN_DEMO, "key", "coins_tickers", _manager(), coin_ids="bitcoin, BITCOIN , bitcoin"))
        assert session.send.call_count == 1


class TestMarketChart:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_zips_the_three_series_into_one_row_per_timestamp(self, MockSession) -> None:
        session = MockSession.return_value
        first, second = 1764547200000, 1764633600000
        _wire(
            session,
            [
                _response(
                    {
                        "prices": [[first, 90832.0], [second, 90360.0]],
                        "market_caps": [[first, 1.5e12], [second, 1.6e12]],
                        "total_volumes": [[first, 1.8e10], [second, 1.9e10]],
                    }
                )
            ],
        )

        start = (_today() - timedelta(days=5)).isoformat()
        rows = _rows(_source(PLAN_PRO, "key", "coins_market_chart", _manager(), coin_ids="bitcoin", start_date=start))

        assert rows == [
            {
                "coin_id": "bitcoin",
                "timestamp": datetime.fromtimestamp(first / 1000, tz=UTC),
                "price": 90832.0,
                "market_cap": 1.5e12,
                "total_volume": 1.8e10,
            },
            {
                "coin_id": "bitcoin",
                "timestamp": datetime.fromtimestamp(second / 1000, tz=UTC),
                "price": 90360.0,
                "market_cap": 1.6e12,
                "total_volume": 1.9e10,
            },
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_series_of_unequal_length_still_line_up(self, MockSession) -> None:
        session = MockSession.return_value
        first, second = 1764547200000, 1764633600000
        # CoinGecko can return a volume point the price series has not caught up with yet.
        _wire(session, [_response({"prices": [[first, 1.0]], "market_caps": [], "total_volumes": [[second, 2.0]]})])

        start = (_today() - timedelta(days=5)).isoformat()
        rows = _rows(_source(PLAN_PRO, "key", "coins_market_chart", _manager(), coin_ids="bitcoin", start_date=start))

        assert [sorted(row.keys()) for row in rows] == [
            ["coin_id", "price", "timestamp"],
            ["coin_id", "timestamp", "total_volume"],
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_object_body_fails_loud(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response("unexpected")])

        start = (_today() - timedelta(days=5)).isoformat()
        with pytest.raises(ValueError, match="market chart object"):
            _rows(_source(PLAN_PRO, "key", "coins_market_chart", _manager(), coin_ids="bitcoin", start_date=start))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pins_daily_granularity_and_usd(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response({"prices": [], "market_caps": [], "total_volumes": []})])

        start = (_today() - timedelta(days=5)).isoformat()
        _rows(_source(PLAN_PRO, "key", "coins_market_chart", _manager(), coin_ids="bitcoin", start_date=start))

        # Without an explicit interval the API picks granularity from the window length, so a short
        # incremental window would return hourly points that don't line up with the synced daily ones.
        assert snaps[0]["params"]["interval"] == "daily"
        assert snaps[0]["params"]["vs_currency"] == "usd"


class TestOhlc:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_maps_candles_onto_rows(self, MockSession) -> None:
        session = MockSession.return_value
        closed_at = 1764547200000
        _wire(session, [_response([[closed_at, 90832.0, 91905.0, 90406.0, 90406.0]])])

        start = (_today() - timedelta(days=5)).isoformat()
        rows = _rows(_source(PLAN_PRO, "key", "coins_ohlc", _manager(), coin_ids="bitcoin", start_date=start))

        assert rows == [
            {
                "coin_id": "bitcoin",
                "timestamp": datetime.fromtimestamp(closed_at / 1000, tz=UTC),
                "open": 90832.0,
                "high": 91905.0,
                "low": 90406.0,
                "close": 90406.0,
            }
        ]

    @parameterized.expand(
        [("short candle", [[1764547200000, 1.0, 2.0]]), ("unparseable timestamp", [["nope", 1.0, 2.0, 3.0, 4.0]])]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unusable_candles_are_dropped(self, _name: str, body: list[Any], MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(body)])

        start = (_today() - timedelta(days=5)).isoformat()
        assert _rows(_source(PLAN_PRO, "key", "coins_ohlc", _manager(), coin_ids="bitcoin", start_date=start)) == []


class TestChartWindows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_splits_a_long_backfill_into_windows_the_api_accepts(self, MockSession) -> None:
        session = MockSession.return_value
        today = _today()
        start = today - timedelta(days=CHART_WINDOW_DAYS + 10)
        snaps = _wire(session, [_response([]) for _ in range(4)])
        _rows(_source(PLAN_PRO, "key", "coins_ohlc", _manager(), coin_ids="bitcoin", start_date=start.isoformat()))

        first_end = start + timedelta(days=CHART_WINDOW_DAYS - 1)
        assert [(snap["params"]["from"], snap["params"]["to"]) for snap in snaps[:2]] == [
            (start.isoformat(), first_end.isoformat()),
            ((first_end + timedelta(days=1)).isoformat(), today.isoformat()),
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_one_batch_holds_every_coin_for_a_window(self, MockSession) -> None:
        session = MockSession.return_value
        today = _today()
        start = today - timedelta(days=CHART_WINDOW_DAYS + 10)
        first_candle, second_candle = 1764547200000, 1764633600000
        snaps = _wire(
            session,
            [
                _response([[first_candle, 1.0, 2.0, 3.0, 4.0]]),
                _response([[first_candle, 5.0, 6.0, 7.0, 8.0]]),
                _response([[second_candle, 1.0, 2.0, 3.0, 4.0]]),
                _response([[second_candle, 5.0, 6.0, 7.0, 8.0]]),
            ],
        )

        manager = _manager()
        source = _source(
            PLAN_PRO, "key", "coins_ohlc", manager, coin_ids="bitcoin,ethereum", start_date=start.isoformat()
        )
        batches = list(source.items())

        # The pipeline commits the incremental watermark to the highest timestamp in each batch, so
        # a batch carrying one coin past a window the other has not been fetched for would let the
        # next job start beyond the coin left behind and skip it for good.
        assert [[row["coin_id"] for row in batch] for batch in batches] == [
            ["bitcoin", "ethereum"],
            ["bitcoin", "ethereum"],
        ]
        # Both coins are fetched for one window before either moves on to the next.
        windows = [snap["params"]["from"] for snap in snaps]
        assert windows[0] == windows[1] and windows[2] == windows[3] and windows[0] != windows[2]
        assert manager.save_state.call_args_list[-1] == mock.call(
            CoinGeckoResumeConfig(next_start=(today + timedelta(days=1)).isoformat())
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_starts_at_the_default_history_window(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response([]) for _ in range(4)])

        # No configured start date and no watermark: the first window must start at the furthest
        # back every plan serves, not at the API's own earliest data.
        _rows(
            _source(
                PLAN_PRO,
                "key",
                "coins_ohlc",
                _manager(),
                coin_ids="bitcoin",
                should_use_incremental_field=False,
                db_incremental_field_last_value="2020-01-01",
            )
        )
        assert snaps[0]["params"]["from"] == (_today() - timedelta(days=DEFAULT_HISTORY_DAYS)).isoformat()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_starts_at_the_last_synced_day(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response([]) for _ in range(4)])

        # Relative to today, so the number of windows between the watermark and now stays fixed
        # however far the real clock moves past this test.
        last_synced_day = _today() - timedelta(days=10)
        _rows(
            _source(
                PLAN_PRO,
                "key",
                "coins_ohlc",
                _manager(),
                coin_ids="bitcoin",
                start_date=(last_synced_day - timedelta(days=400)).isoformat(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime.combine(last_synced_day, time(9, 30), tzinfo=UTC),
            )
        )
        # Re-reads the last synced day rather than starting after it: that day was still moving
        # when it first landed, and merge dedupes the overlap.
        assert snaps[0]["params"]["from"] == last_synced_day.isoformat()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_start_date_is_floored(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response([[1764547200000, 1.0, 2.0, 3.0, 4.0]])])

        # A configuration stored before the floor existed must not schedule an unbounded backfill.
        # Only the first window is pulled here; the rest would run all the way to today.
        pages = _source(PLAN_PRO, "key", "coins_ohlc", _manager(), coin_ids="bitcoin", start_date="0001-01-01").items()
        next(iter(pages))

        assert snaps[0]["params"]["from"] == "2018-01-01"
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_at_the_saved_window(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response([]) for _ in range(4)])

        resumed_from = (_today() - timedelta(days=3)).isoformat()
        manager = _manager(CoinGeckoResumeConfig(next_start=resumed_from))
        _rows(
            _source(
                PLAN_PRO,
                "key",
                "coins_ohlc",
                manager,
                coin_ids="bitcoin,ethereum",
                start_date=(_today() - timedelta(days=300)).isoformat(),
            )
        )

        # The saved window is re-fetched for every coin, so resuming cannot drop one of them.
        assert session.send.call_count == 2
        assert [snap["params"]["from"] for snap in snaps[:2]] == [resumed_from, resumed_from]
        assert snaps[0]["url"].endswith("/coins/bitcoin/ohlc/range")
        assert snaps[1]["url"].endswith("/coins/ethereum/ohlc/range")


class TestExchangeRates:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_flattens_the_rates_object_into_a_row_per_currency(self, MockSession) -> None:
        session = MockSession.return_value
        # The body is keyed by currency code rather than being a row list, so without the flattening
        # the whole object would land as one unusable row.
        _wire(
            session,
            [
                _response(
                    {
                        "rates": {
                            "btc": {"name": "Bitcoin", "unit": "BTC", "value": 1.0, "type": "crypto"},
                            "usd": {"name": "US Dollar", "unit": "$", "value": 80443.4, "type": "fiat"},
                        }
                    }
                )
            ],
        )

        rows = _rows(_source(PLAN_DEMO, "key", "exchange_rates", _manager()))

        assert rows == [
            {"id": "btc", "name": "Bitcoin", "unit": "BTC", "value": 1.0, "type": "crypto"},
            {"id": "usd", "name": "US Dollar", "unit": "$", "value": 80443.4, "type": "fiat"},
        ]
        assert session.send.call_count == 1


class TestGlobalMarketCapChart:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_zips_the_two_series_into_one_row_per_timestamp(self, MockSession) -> None:
        session = MockSession.return_value
        first, second = 1764547200000, 1764633600000
        _wire(
            session,
            [
                _response(
                    {
                        "market_cap_chart": {
                            "market_cap": [[first, 2.6e12], [second, 2.7e12]],
                            "volume": [[first, 7.2e10], [second, 7.3e10]],
                        }
                    }
                )
            ],
        )

        rows = _rows(_source(PLAN_PRO, "key", "global_market_cap_chart", _manager()))

        assert rows == [
            {"timestamp": datetime.fromtimestamp(first / 1000, tz=UTC), "market_cap": 2.6e12, "volume": 7.2e10},
            {"timestamp": datetime.fromtimestamp(second / 1000, tz=UTC), "market_cap": 2.7e12, "volume": 7.3e10},
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_asks_for_the_whole_history(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response({"market_cap_chart": {"market_cap": [], "volume": []}})])

        _rows(
            _source(
                PLAN_PRO,
                "key",
                "global_market_cap_chart",
                _manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value=datetime.now(UTC),
            )
        )
        # A full refresh must ignore the stored watermark, or it would resync a narrow window and
        # leave the rest of the table behind.
        assert snaps[0]["params"]["days"] == "max"

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
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_narrows_the_window_to_the_watermark(
        self, _name: str, days_behind: int, expected_days: str, MockSession
    ) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response({"market_cap_chart": {"market_cap": [], "volume": []}})])

        _rows(
            _source(
                PLAN_PRO,
                "key",
                "global_market_cap_chart",
                _manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime.combine(
                    _today() - timedelta(days=days_behind), time(9, 30), tzinfo=UTC
                ),
            )
        )
        assert snaps[0]["params"]["days"] == expected_days


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
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unexpected_shape_fails_loud(
        self, _name: str, endpoint: str, body: Any, expected_message: str, MockSession
    ) -> None:
        session = MockSession.return_value
        # These bodies are reshaped rather than yielded as rows, so a changed shape must fail rather
        # than silently syncing zero rows or one garbage row.
        _wire(session, [_response(body)])

        with pytest.raises(ValueError, match=expected_message):
            _rows(_source(PLAN_PRO, "key", endpoint, _manager()))
