from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kalshi import KalshiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.source import KalshiSource


class TestKalshiSource:
    @parameterized.expand(
        [
            ("trades_is_incremental", "trades", True),
            ("historical_trades_is_incremental", "historical_trades", True),
            ("market_candlesticks_is_incremental", "market_candlesticks", True),
            ("weather_index_is_incremental", "weather_index", True),
            ("markets_is_not", "markets", False),
            ("historical_markets_is_not", "historical_markets", False),
            ("events_is_not", "events", False),
            ("series_is_not", "series", False),
            ("milestones_is_not", "milestones", False),
        ]
    )
    def test_only_time_filtered_endpoints_support_incremental(self, _name: str, endpoint: str, expected: bool) -> None:
        # Only the trade and candlestick endpoints honour a server-side time filter. Advertising
        # incremental anywhere else would promise a cheap sync that still walks the whole collection.
        schemas = {s.name: s for s in KalshiSource().get_schemas(None, 1)}  # type: ignore[arg-type]

        assert schemas[endpoint].supports_incremental is expected

    @parameterized.expand([("reachable", True, True), ("unreachable", False, False)])
    def test_validate_credentials(self, _name: str, probe_ok: bool, expected: bool) -> None:
        status = 200 if probe_ok else 403
        with scripted_network([ScriptedResponse(status=status)]) as network:
            ok, message = KalshiSource().validate_credentials(KalshiSourceConfig(), 1)

        assert ok is expected
        assert (message is None) is expected
        assert network.requests_log[0].path == "/trade-api/v2/exchange/status"

    def test_source_for_pipeline_drops_the_watermark_on_full_refresh(self) -> None:
        # A stale watermark leaking into a full refresh would filter rows the user asked to re-import.
        result = SourceDriver(KalshiSource(), KalshiSourceConfig()).run(
            "trades",
            [ScriptedResponse(json={"trades": [{"trade_id": "t1"}]})],
            should_use_incremental_field=False,
            db_incremental_field_last_value=123,
        )

        assert result.raised is None
        assert result.requests[0].param("min_ts") is None
        assert result.rows == [{"trade_id": "t1"}]
