import base64
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kalshi import KalshiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.kalshi import (
    INVALID_PRIVATE_KEY_MESSAGE,
    KalshiCredentialsError,
    KalshiResumeConfig,
    KalshiSignedAuth,
    _batch_markets,
    _candlestick_market,
    _CandlestickMarket,
    _to_epoch_seconds,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.settings import (
    KALSHI_ENDPOINTS,
    WEATHER_INDEX_CITIES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.source import KalshiSource


def _pem(key: PrivateKeyTypes) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


_RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_ED25519_KEY = ed25519.Ed25519PrivateKey.generate()


def _driver() -> SourceDriver:
    return SourceDriver(KalshiSource(), KalshiSourceConfig(api_key_id="key-id", private_key=_pem(_RSA_KEY)))


def _verify(key: PrivateKeyTypes, signature: bytes, message: bytes) -> bool:
    try:
        if isinstance(key, ed25519.Ed25519PrivateKey):
            key.public_key().verify(signature, message)
        else:
            assert isinstance(key, rsa.RSAPrivateKey)
            key.public_key().verify(
                signature,
                message,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
                hashes.SHA256(),
            )
    except InvalidSignature:
        return False
    return True


def _page(data_key: str, items: list[dict[str, Any]], *, cursor: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {data_key: items}
    if cursor is not None:
        body["cursor"] = cursor
    return ScriptedResponse(json=body)


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp())


def _market(ticker: str, opened: datetime, closes: datetime) -> dict[str, Any]:
    return {"ticker": ticker, "open_time": opened.isoformat(), "close_time": closes.isoformat()}


def _candlesticks(*markets: tuple[str, list[int]]) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "markets": [
                {"market_ticker": ticker, "candlesticks": [{"end_period_ts": ts, "volume_fp": "1.00"} for ts in ends]}
                for ticker, ends in markets
            ]
        }
    )


class TestKalshiTransport:
    @parameterized.expand(
        [
            ("datetime", datetime(2021, 1, 1, tzinfo=UTC), 1609459200),
            ("date", date(2021, 1, 1), 1609459200),
            ("int_passthrough", 1609459200, 1609459200),
            ("iso_string", "2021-01-01T00:00:00+00:00", 1609459200),
            ("iso_string_z", "2021-01-01T00:00:00Z", 1609459200),
            ("none", None, None),
            ("garbage", "not-a-date", None),
        ]
    )
    def test_to_epoch_seconds(self, _name: str, value: Any, expected: int | None) -> None:
        # min_ts is epoch seconds; sending an ISO string instead would be silently ignored by the
        # API and quietly turn every incremental sync into a full scan.
        assert _to_epoch_seconds(value) == expected

    @parameterized.expand(
        [
            ("trades", "/trade-api/v2/markets/trades", "created_time"),
            ("historical_trades", "/trade-api/v2/historical/trades", "created_time"),
            ("fills", "/trade-api/v2/portfolio/fills", "created_time"),
            ("historical_fills", "/trade-api/v2/historical/fills", "created_time"),
        ]
    )
    def test_trades_incremental_sends_min_ts(self, endpoint: str, path: str, incremental_field: str) -> None:
        result = _driver().run(
            endpoint,
            [_page(KALSHI_ENDPOINTS[endpoint].data_key, [{"id": "1"}])],
            incremental_field=incremental_field,
            db_incremental_field_last_value=datetime(2021, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.paths == [path]
        assert result.requests[0].param("min_ts") == "1609459200"
        assert result.requests[0].param("limit") == str(KALSHI_ENDPOINTS[endpoint].page_size)

    @parameterized.expand(["markets", "events", "milestones", "historical_markets", "orders", "historical_orders"])
    def test_non_incremental_endpoints_never_send_min_ts(self, endpoint: str) -> None:
        # Kalshi answers 200 and ignores params it doesn't recognise, so a filter wired onto an
        # endpoint that has none would look like it worked while syncing everything every run.
        result = _driver().run(
            endpoint,
            [_page(KALSHI_ENDPOINTS[endpoint].data_key, [{"id": "1"}])],
            incremental_field="created_time",
            db_incremental_field_last_value=datetime(2021, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("min_ts") is None

    def test_cursor_pagination_walks_then_stops(self) -> None:
        result = _driver().run(
            "markets",
            [
                _page("markets", [{"ticker": "A"}], cursor="c1"),
                _page("markets", [{"ticker": "B"}], cursor="c2"),
                # No cursor on the final page.
                _page("markets", [{"ticker": "C"}]),
            ],
        )

        assert result.raised is None
        assert [row["ticker"] for row in result.rows] == ["A", "B", "C"]
        # The first request carries no cursor; each later one carries the previous response's.
        assert result.params("cursor") == [None, "c1", "c2"]

    def test_resume_seeds_cursor_onto_first_request(self) -> None:
        result = _driver().run(
            "markets",
            [_page("markets", [{"ticker": "B"}])],
            resume_state=KalshiResumeConfig(cursor="saved"),
        )

        assert result.raised is None
        assert result.requests[0].param("cursor") == "saved"

    @parameterized.expand(
        [
            ("trades", "desc"),
            ("historical_trades", "desc"),
            ("fills", "desc"),
            ("markets", "asc"),
            ("series", "asc"),
        ]
    )
    def test_sort_mode_matches_api_order(self, endpoint: str, expected: str) -> None:
        # Trades arrive newest-first. Declaring "asc" would checkpoint the watermark to ~now after
        # the first batch and skip the rest of the backfill.
        result = _driver().run(endpoint, [_page(KALSHI_ENDPOINTS[endpoint].data_key, [])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.sort_mode == expected

    @parameterized.expand(
        [
            ("markets", ["ticker"]),
            ("events", ["event_ticker"]),
            ("series", ["ticker"]),
            ("trades", ["trade_id"]),
            ("milestones", ["id"]),
        ]
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, expected: list[str]) -> None:
        # A wrong key seeds duplicate rows that every later merge multi-matches.
        result = _driver().run(endpoint, [_page(KALSHI_ENDPOINTS[endpoint].data_key, [])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.primary_keys == expected

    @parameterized.expand(
        [
            ("trades", ["created_time"]),
            ("markets", ["created_time"]),
            ("series", None),
        ]
    )
    def test_partitioning_only_where_a_stable_key_exists(self, endpoint: str, expected: list[str] | None) -> None:
        result = _driver().run(endpoint, [_page(KALSHI_ENDPOINTS[endpoint].data_key, [])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.partition_keys == expected
        assert result.response.partition_mode == ("datetime" if expected else None)

    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_validate_credentials_maps_status(self, _name: str, status: int, expected: bool) -> None:
        answer = ScriptedResponse(status=status)
        script = always(answer) if status == 500 else [answer]
        with scripted_network(script) as network:
            assert validate_credentials() is expected

        assert network.requests_log[0].path == "/trade-api/v2/exchange/status"


class TestKalshiPortfolio:
    @parameterized.expand([("rsa", _RSA_KEY), ("ed25519", _ED25519_KEY)])
    def test_signs_method_and_path_without_the_query(self, _name: str, key: PrivateKeyTypes) -> None:
        driver = SourceDriver(KalshiSource(), KalshiSourceConfig(api_key_id="key-id", private_key=_pem(key)))
        result = driver.run("fills", [_page("fills", [{"fill_id": "f1"}])])

        assert result.raised is None
        request = result.requests[0]
        assert request.param("limit") == "1000"
        assert request.headers["kalshi-access-key"] == "key-id"
        message = f"{request.headers['kalshi-access-timestamp']}GET/trade-api/v2/portfolio/fills".encode()
        assert _verify(key, base64.b64decode(request.headers["kalshi-access-signature"]), message)

    def test_public_endpoints_are_not_signed(self) -> None:
        result = _driver().run("markets", [_page("markets", [{"ticker": "A"}])])

        assert result.raised is None
        assert "kalshi-access-signature" not in result.requests[0].headers

    @parameterized.expand(
        [
            ("no_key", None, None),
            ("key_id_only", "key-id", None),
        ]
    )
    def test_portfolio_endpoint_without_a_key_fails_before_any_request(
        self, _name: str, api_key_id: str | None, private_key: str | None
    ) -> None:
        driver = SourceDriver(KalshiSource(), KalshiSourceConfig(api_key_id=api_key_id, private_key=private_key))
        result = driver.run("orders", [_page("orders", [])])

        assert isinstance(result.raised, KalshiCredentialsError)
        assert result.requests == []

    @parameterized.expand(
        [
            ("not_pem", "not a key"),
            ("unsupported_type", _pem(ec.generate_private_key(ec.SECP256R1()))),
        ]
    )
    def test_rejects_an_invalid_private_key(self, _name: str, private_key: str) -> None:
        with pytest.raises(KalshiCredentialsError, match=INVALID_PRIVATE_KEY_MESSAGE):
            KalshiSignedAuth("key-id", private_key)

    @parameterized.expand(
        [
            ("positions", "/trade-api/v2/portfolio/positions", "market_positions", "all"),
            ("historical_positions", "/trade-api/v2/historical/positions", "market_positions", None),
            ("settlements", "/trade-api/v2/portfolio/settlements", "settlements", None),
        ]
    )
    def test_subaccount_endpoints_read_every_subaccount(
        self, endpoint: str, path: str, data_key: str, settlement_status: str | None
    ) -> None:
        # Positions default to subaccount 0, and settlement rows carry no subaccount, so each
        # subaccount is read on its own and stamped onto its rows.
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json={"subaccount_balances": [{"subaccount_number": 3}, {"subaccount_number": 0}]}),
                _page(data_key, [{"ticker": "A"}], cursor="c1"),
                _page(data_key, [{"ticker": "B"}]),
                _page(data_key, [{"ticker": "A"}]),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/trade-api/v2/portfolio/subaccounts/balances", path, path, path]
        assert result.params("subaccount") == [None, "0", "0", "3"]
        assert result.params("cursor") == [None, None, "c1", None]
        assert result.params("settlement_status") == [None, settlement_status, settlement_status, settlement_status]
        assert [(row["subaccount_number"], row["ticker"]) for row in result.rows] == [(0, "A"), (0, "B"), (3, "A")]
        assert result.response is not None
        assert result.response.primary_keys == ["subaccount_number", "ticker"]

    def test_settlements_incremental_sends_min_ts_for_each_subaccount(self) -> None:
        result = _driver().run(
            "settlements",
            [
                ScriptedResponse(json={"subaccount_balances": [{"subaccount_number": 0}, {"subaccount_number": 1}]}),
                _page("settlements", [{"ticker": "A"}]),
                _page("settlements", [{"ticker": "B"}]),
            ],
            incremental_field="settled_time",
            db_incremental_field_last_value=datetime(2021, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params("min_ts") == [None, "1609459200", "1609459200"]
        assert result.response is not None
        assert result.response.sort_mode == "desc"

    def test_subaccount_walk_resumes_and_stages_the_next_subaccount(self) -> None:
        result = _driver().run(
            "positions",
            [
                ScriptedResponse(json={"subaccount_balances": [{"subaccount_number": n} for n in (0, 1, 2)]}),
                _page("market_positions", [{"ticker": "B"}]),
                _page("market_positions", [{"ticker": "C"}]),
            ],
            resume_state=KalshiResumeConfig(cursor="saved", subaccount=1),
        )

        assert result.raised is None
        assert result.params("subaccount") == [None, "1", "2"]
        assert result.params("cursor") == [None, "saved", None]
        assert KalshiResumeConfig(cursor="", subaccount=2) in result.committed_states


class TestKalshiCandlesticks:
    def test_walks_market_pages_and_batches_candlestick_requests(self) -> None:
        now = datetime.now(UTC)
        opened_a, opened_b = now - timedelta(days=3), now - timedelta(days=10)
        closes = now + timedelta(days=30)
        result = _driver().run(
            "market_candlesticks",
            route(
                {
                    "/markets": [
                        _page(
                            "markets",
                            [
                                _market("A", opened_a, closes),
                                _market("B", opened_b, closes),
                                # Not open yet, so it has no candlesticks to fetch.
                                _market("LATER", now + timedelta(days=1), closes),
                            ],
                            cursor="c1",
                        ),
                        _page("markets", [_market("C", opened_a, closes)]),
                    ],
                    "/candlesticks": [
                        _candlesticks(("A", [100, 200]), ("B", [300])),
                        _candlesticks(("C", [])),
                    ],
                }
            ),
            should_use_incremental_field=False,
        )

        assert result.raised is None
        assert result.paths == [
            "/trade-api/v2/markets",
            "/trade-api/v2/markets/candlesticks",
            "/trade-api/v2/markets",
            "/trade-api/v2/markets/candlesticks",
        ]
        assert result.params("cursor") == [None, None, "c1", None]
        assert result.params("mve_filter") == ["exclude", None, "exclude", None]
        assert result.params("min_close_ts") == [None, None, None, None]
        assert result.params("market_tickers") == [None, "A,B", None, "C"]
        assert result.params("start_ts") == [None, str(_epoch(opened_b)), None, str(_epoch(opened_a))]
        assert result.params("period_interval") == [None, "1440", None, "1440"]
        assert result.rows == [
            {"market_ticker": "A", "end_period_ts": 100, "volume_fp": "1.00"},
            {"market_ticker": "A", "end_period_ts": 200, "volume_fp": "1.00"},
            {"market_ticker": "B", "end_period_ts": 300, "volume_fp": "1.00"},
        ]
        assert result.response is not None
        assert result.response.sort_mode == "desc"

    @parameterized.expand(
        [
            ("watermark_after_open", 5, 3),
            ("watermark_before_open", 30, 3),
        ]
    )
    def test_incremental_sync_windows_markets_and_candlesticks(
        self, _name: str, opened_days_ago: int, watermark_days_ago: int
    ) -> None:
        now = datetime.now(UTC)
        opened = now - timedelta(days=opened_days_ago)
        watermark = _epoch(now - timedelta(days=watermark_days_ago))
        window_start = watermark - 86400
        result = _driver().run(
            "market_candlesticks",
            route(
                {
                    "/markets": [_page("markets", [_market("A", opened, now + timedelta(days=1))])],
                    "/candlesticks": [_candlesticks(("A", [watermark + 86400]))],
                }
            ),
            incremental_field="end_period_ts",
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        assert result.params("min_close_ts") == [str(window_start), None]
        assert result.params("start_ts") == [None, str(max(_epoch(opened), window_start))]
        assert result.rows == [{"market_ticker": "A", "end_period_ts": watermark + 86400, "volume_fp": "1.00"}]

    def test_refetches_a_batch_in_halves_when_the_response_hits_the_cap(self) -> None:
        now = datetime.now(UTC)
        opened, closes = now - timedelta(days=2), now + timedelta(days=1)
        result = _driver().run(
            "market_candlesticks",
            route(
                {
                    "/markets": [_page("markets", [_market("A", opened, closes), _market("B", opened, closes)])],
                    "/candlesticks": [
                        _candlesticks(("A", list(range(5_000))), ("B", list(range(5_000)))),
                        _candlesticks(("A", [1])),
                        _candlesticks(("B", [2])),
                    ],
                }
            ),
            should_use_incremental_field=False,
        )

        assert result.raised is None
        assert result.params("market_tickers") == [None, "A,B", "A", "B"]
        assert [(row["market_ticker"], row["end_period_ts"]) for row in result.rows] == [("A", 1), ("B", 2)]

    def test_resumes_from_the_saved_market_page_and_stages_each_page_cursor(self) -> None:
        now = datetime.now(UTC)
        opened, closes = now - timedelta(days=2), now + timedelta(days=1)
        result = _driver().run(
            "market_candlesticks",
            route(
                {
                    "/markets": [
                        _page("markets", [_market("A", opened, closes)], cursor="c2"),
                        _page("markets", [_market("B", opened, closes)]),
                    ],
                    "/candlesticks": [_candlesticks(("A", [1])), _candlesticks(("B", [2]))],
                }
            ),
            should_use_incremental_field=False,
            resume_state=KalshiResumeConfig(cursor="saved"),
        )

        assert result.raised is None
        assert result.params("cursor") == ["saved", None, "c2", None]
        # Each cursor is staged before the rows of the page it fetched, so a resume rereads that page.
        assert result.saved_states == [KalshiResumeConfig(cursor="saved"), KalshiResumeConfig(cursor="c2")]
        assert KalshiResumeConfig(cursor="c2") in result.committed_states

    @parameterized.expand(
        [
            ("open_market", 10, 5, None, (-10, 0)),
            ("closed_market_ends_at_close", 10, -2, None, (-10, -2)),
            ("window_after_open", 10, 5, -3, (-3, 0)),
            ("not_open_yet", -1, 5, None, None),
            ("closed_before_window", 10, -5, -3, None),
        ]
    )
    def test_candlestick_market_window(
        self,
        _name: str,
        opened_days_ago: int,
        closes_in_days: int,
        window_days: int | None,
        expected_days: tuple[int, int] | None,
    ) -> None:
        now = 1_800_000_000
        day = 86400
        market = {
            "ticker": "A",
            "open_time": datetime.fromtimestamp(now - opened_days_ago * day, UTC).isoformat(),
            "close_time": datetime.fromtimestamp(now + closes_in_days * day, UTC).isoformat(),
        }
        window_start = None if window_days is None else now + window_days * day

        result = _candlestick_market(market, window_start, now)

        if expected_days is None:
            assert result is None
        else:
            assert result == _CandlestickMarket(
                ticker="A", start_ts=now + expected_days[0] * day, end_ts=now + expected_days[1] * day
            )

    @parameterized.expand(
        [
            # 150 short-lived markets split on the 100-ticker limit.
            ("ticker_limit", 150, 1, [100, 50]),
            # Each market can return about 1,002 candlesticks, so 9 fit under the 10,000 cap.
            ("candlestick_cap", 20, 1000, [9, 9, 2]),
            # One market alone over the cap still gets a request of its own.
            ("single_oversized_market", 2, 20_000, [1, 1]),
        ]
    )
    def test_batches_respect_ticker_and_candlestick_limits(
        self, _name: str, count: int, days: int, expected_sizes: list[int]
    ) -> None:
        markets = [_CandlestickMarket(ticker=str(i), start_ts=0, end_ts=days * 86400) for i in range(count)]

        assert [len(batch) for batch in _batch_markets(markets)] == expected_sizes


class TestKalshiWeatherIndex:
    @parameterized.expand(
        [
            # `from=0` would silently fall back to the trailing 24 hours.
            ("full_refresh", {"should_use_incremental_field": False}, "1"),
            (
                "incremental_rereads_the_last_hour",
                {"incremental_field": "t", "db_incremental_field_last_value": 1_790_000_000_000},
                str(1_790_000_000_000 - 3_600_000),
            ),
        ]
    )
    def test_reads_every_city_from_the_window_start(
        self, _name: str, inputs: dict[str, Any], expected_from: str
    ) -> None:
        point = {"t": 1_790_000_060_000, "v": 79.16, "status": "normal", "contributors": 5}
        result = _driver().run(
            "weather_index",
            always(ScriptedResponse(json={"city": "any", "units": "fahrenheit", "timeseries": [point]})),
            **inputs,
        )

        assert result.raised is None
        assert result.paths == [f"/trade-api/v2/live_data/weather/{city}" for city in WEATHER_INDEX_CITIES]
        assert set(result.params("from")) == {expected_from}
        assert all(to is not None for to in result.params("to"))
        # The city is half of the primary key; without it every city's minute collides.
        assert result.rows == [{"city": city, **point} for city in WEATHER_INDEX_CITIES]
        assert result.response is not None
        assert result.response.sort_mode == "desc"

    def test_resumes_from_the_saved_city_and_stages_the_next_one(self) -> None:
        result = _driver().run(
            "weather_index",
            always(ScriptedResponse(json={"city": "any", "units": "fahrenheit", "timeseries": [{"t": 1, "v": 1.0}]})),
            resume_state=KalshiResumeConfig(cursor=WEATHER_INDEX_CITIES[-2]),
            should_use_incremental_field=False,
        )

        assert result.raised is None
        assert result.paths == [f"/trade-api/v2/live_data/weather/{city}" for city in WEATHER_INDEX_CITIES[-2:]]
        assert result.saved_states[-1] == KalshiResumeConfig(cursor=WEATHER_INDEX_CITIES[-1])
