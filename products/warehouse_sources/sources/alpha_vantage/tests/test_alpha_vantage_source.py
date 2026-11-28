from parameterized import parameterized

from products.warehouse_sources.sources.alpha_vantage._config import AlphaVantageSourceConfig
from products.warehouse_sources.sources.alpha_vantage.source import AlphaVantageSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, scripted_network


def _make_config(api_key: str = "key", symbols: str = "IBM, AAPL") -> AlphaVantageSourceConfig:
    return AlphaVantageSourceConfig(api_key=api_key, symbols=symbols)


class TestAlphaVantageSource:
    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs can render tables.
        assert AlphaVantageSource.lists_tables_without_credentials is True

    @parameterized.expand(
        [
            ("enabled_null", None, {"earnings_call_transcript"}, False),
            ("enabled_valid", "2024Q1", {"earnings_call_transcript"}, True),
            ("disabled_empty", "", {"earnings_calendar"}, True),
        ]
    )
    def test_validate_sync_config_checks_quarter_for_enabled_transcripts(
        self, _name: str, quarter: str | None, enabled_schemas: set[str], expected_valid: bool
    ) -> None:
        config = AlphaVantageSourceConfig(api_key="KEY", symbols="ACME", transcript_quarter=quarter)

        error = AlphaVantageSource().validate_sync_config(lambda: config, enabled_schemas.__contains__)

        assert (error is None) is expected_valid

    @parameterized.expand(
        [
            ("valid", "KEY", "IBM", True, True, None),
            ("invalid_key", "KEY", "IBM", False, False, "Invalid Alpha Vantage API key"),
            ("no_symbols", "KEY", "  ", True, False, "Enter at least one symbol (e.g. IBM, AAPL)"),
            (
                "too_many_symbols",
                "KEY",
                ",".join(f"S{i}" for i in range(101)),
                True,
                False,
                "Too many symbols (101); enter at most 100 distinct symbols.",
            ),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        api_key: str,
        symbols: str,
        probe_result: bool,
        expected_ok: bool,
        expected_message: str | None,
    ) -> None:
        body = {"Global Quote": {"01. symbol": "IBM"}} if probe_result else {"Error Message": "invalid apikey"}
        with scripted_network([ScriptedResponse(json=body)]) as network:
            ok, message = AlphaVantageSource().validate_credentials(_make_config(api_key, symbols), team_id=1)
        assert ok is expected_ok
        assert message == expected_message
        assert len(network.requests_log) == (0 if not symbols.strip() or len(symbols.split(",")) > 100 else 1)

    @parameterized.expand(
        [
            ("incremental", True, "2026-08-01", "2026-08-01"),
            # A full refresh must not carry the stored watermark, or it would filter the API call.
            ("full_refresh", False, "2026-08-01", None),
        ]
    )
    def test_source_for_pipeline_plumbs_symbols_key_and_watermark(
        self, _name: str, should_use_incremental_field: bool, last_value: str, expected_watermark: str | None
    ) -> None:
        result = SourceDriver(AlphaVantageSource(), _make_config("abc", "ibm, aapl")).run(
            "insider_transactions",
            [ScriptedResponse(json={"data": []}), ScriptedResponse(json={"data": []})],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )
        assert result.raised is None
        assert result.params("apikey") == ["abc", "abc"]
        # Symbols are parsed (upper-cased, de-duplicated) before handing off to the transport.
        assert result.params("symbol") == ["IBM", "AAPL"]
        assert result.params("function") == ["INSIDER_TRANSACTIONS", "INSIDER_TRANSACTIONS"]
        assert result.params("from") == [expected_watermark, expected_watermark]

    def test_source_for_pipeline_rejects_oversized_symbol_list(self) -> None:
        # A previously-saved oversized config must fail the run instead of fanning out into a runaway sync.
        oversized = _make_config("abc", ",".join(f"S{i}" for i in range(101)))
        result = SourceDriver(AlphaVantageSource(), oversized).run("time_series_daily", [])
        assert isinstance(result.raised, ValueError)
        assert "Too many symbols" in str(result.raised)
        assert result.requests == []

    def test_transcript_uses_configured_fiscal_quarter_and_retains_turn_order(self) -> None:
        config = AlphaVantageSourceConfig(api_key="KEY", symbols="ACME", transcript_quarter=" 2024q1 ")
        turns = [
            {"speaker": "Speaker A", "title": "Host", "content": "Welcome.", "sentiment": "0.6"},
            {"speaker": "Speaker A", "title": "Host", "content": "First question, please.", "sentiment": "0.0"},
        ]
        result = SourceDriver(AlphaVantageSource(), config).run(
            "earnings_call_transcript", [ScriptedResponse(json={"quarter": "2024Q1", "transcript": turns})]
        )

        assert result.raised is None
        assert result.params("function") == ["EARNINGS_CALL_TRANSCRIPT"]
        assert result.params("symbol") == ["ACME"]
        assert result.params("quarter") == ["2024Q1"]
        assert result.rows == [
            {**turn, "symbol": "ACME", "quarter": "2024Q1", "turn_index": turn_index}
            for turn_index, turn in enumerate(turns)
        ]

    @parameterized.expand([("missing", None), ("invalid", "2024Q5"), ("too_early", "2009Q4")])
    def test_transcript_rejects_invalid_quarter_before_request(self, _name: str, quarter: str | None) -> None:
        config = AlphaVantageSourceConfig(api_key="KEY", symbols="ACME", transcript_quarter=quarter)
        source = AlphaVantageSource()
        with scripted_network([]) as network:
            ok, message = source.validate_credentials(config, team_id=1, schema_name="earnings_call_transcript")
        assert not ok
        assert message is not None and "2024Q1" in message
        assert network.requests_log == []

        result = SourceDriver(source, config).run("earnings_call_transcript", [])
        assert isinstance(result.raised, ValueError)
        assert str(result.raised) == message
        assert result.requests == []
