from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.alpha_vantage.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.alpha_vantage.source import AlphaVantageSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.alpha_vantage.source"


def _make_config(api_key: str = "key", symbols: str = "IBM, AAPL") -> Any:
    config = MagicMock()
    config.api_key = api_key
    config.symbols = symbols
    return config


class TestAlphaVantageSource:
    def test_source_config_has_api_key_and_symbols_fields(self) -> None:
        config = AlphaVantageSource().get_source_config
        assert [f.name for f in config.fields] == ["api_key", "symbols"]
        api_key_field, symbols_field = config.fields
        assert isinstance(api_key_field, SourceFieldInputConfig)
        # The API key is a secret credential, so it must render as a password input.
        assert api_key_field.type == "password"
        assert api_key_field.secret is True
        assert api_key_field.required is True
        # Symbols are not secret and drive the per-symbol fan-out.
        assert isinstance(symbols_field, SourceFieldInputConfig)
        assert symbols_field.type == "text"
        assert symbols_field.secret is False
        assert symbols_field.required is True

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs can render tables.
        assert AlphaVantageSource.lists_tables_without_credentials is True

    def test_get_schemas_marks_only_the_server_filtered_endpoints_incremental(self) -> None:
        schemas = {s.name: s for s in AlphaVantageSource().get_schemas(_make_config(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS)
        # Only NEWS_SENTIMENT (`time_from`) and INSIDER_TRANSACTIONS (`from`) filter server-side. A
        # table that lost its cursor here would silently re-pull its whole history every sync; one that
        # gained a bogus cursor would checkpoint a watermark the API never honoured.
        incremental = {name for name, schema in schemas.items() if schema.supports_incremental}
        assert incremental == {"news_sentiment", "insider_transactions"}
        assert [f["field"] for f in schemas["news_sentiment"].incremental_fields] == ["time_published"]
        assert [f["field"] for f in schemas["insider_transactions"].incremental_fields] == ["transaction_date"]
        assert all(not schemas[name].incremental_fields for name in set(ENDPOINTS) - incremental)
        # Both filters are coarser than the stored cursor, so every run re-delivers the boundary rows
        # and only a merge can dedupe them — append would duplicate.
        assert all(schema.supports_append is False for schema in schemas.values())

    def test_get_schemas_exposes_primary_keys(self) -> None:
        schemas = {s.name: s for s in AlphaVantageSource().get_schemas(_make_config(), team_id=1)}
        assert schemas["time_series_daily"].detected_primary_keys == ["symbol", "date"]
        assert schemas["income_statement"].detected_primary_keys == ["symbol", "fiscalDateEnding", "report_type"]
        assert schemas["global_quote"].detected_primary_keys == ["symbol"]

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = AlphaVantageSource().get_schemas(_make_config(), team_id=1, names=["earnings", "global_quote"])
        assert {s.name for s in schemas} == {"earnings", "global_quote"}

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
        with patch(f"{MODULE}.validate_alpha_vantage_credentials", return_value=probe_result):
            ok, message = AlphaVantageSource().validate_credentials(_make_config(api_key, symbols), team_id=1)
        assert ok is expected_ok
        assert message == expected_message

    def test_validate_credentials_skips_probe_without_symbols(self) -> None:
        # No point probing the API key if there are no symbols to sync — fail fast on symbols first.
        with patch(f"{MODULE}.validate_alpha_vantage_credentials") as probe:
            ok, _ = AlphaVantageSource().validate_credentials(_make_config(symbols=""), team_id=1)
        assert ok is False
        probe.assert_not_called()

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
        inputs = MagicMock()
        inputs.schema_name = "insider_transactions"
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = should_use_incremental_field
        inputs.db_incremental_field_last_value = last_value
        with patch(f"{MODULE}.alpha_vantage_source") as source_fn:
            AlphaVantageSource().source_for_pipeline(_make_config("abc", "ibm, aapl"), inputs)
        source_fn.assert_called_once()
        kwargs = source_fn.call_args.kwargs
        assert kwargs["api_key"] == "abc"
        # Symbols are parsed (upper-cased, de-duplicated) before handing off to the transport.
        assert kwargs["symbols"] == ["IBM", "AAPL"]
        assert kwargs["endpoint"] == "insider_transactions"
        assert kwargs["db_incremental_field_last_value"] == expected_watermark

    def test_source_for_pipeline_rejects_oversized_symbol_list(self) -> None:
        # A previously-saved oversized config must fail the run instead of fanning out into a runaway sync.
        inputs = MagicMock()
        inputs.schema_name = "time_series_daily"
        inputs.logger = MagicMock()
        oversized = _make_config("abc", ",".join(f"S{i}" for i in range(101)))
        with patch(f"{MODULE}.alpha_vantage_source") as source_fn:
            with pytest.raises(ValueError, match="Too many symbols"):
                AlphaVantageSource().source_for_pipeline(oversized, inputs)
        source_fn.assert_not_called()

    def test_canonical_descriptions_keyed_by_endpoint(self) -> None:
        descriptions = AlphaVantageSource().get_canonical_descriptions()
        # Every documented entry must map to a real endpoint or the docs render orphaned tables.
        assert set(descriptions.keys()) <= set(ENDPOINTS)
        assert "time_series_daily" in descriptions
        assert "earnings" in descriptions
