from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.alpha_vantage.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.alpha_vantage.source import AlphaVantageSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.alpha_vantage.source"


def _make_config(api_key: str = "key", symbols: str = "IBM, AAPL") -> Any:
    config = MagicMock()
    config.api_key = api_key
    config.symbols = symbols
    return config


class TestAlphaVantageSource:
    def test_source_type(self) -> None:
        assert AlphaVantageSource().source_type == ExternalDataSourceType.ALPHAVANTAGE

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

    def test_source_config_stays_unreleased_alpha(self) -> None:
        config = AlphaVantageSource().get_source_config
        assert config.unreleasedSource is True
        assert config.releaseStatus == "alpha"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/alpha-vantage"

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs can render tables.
        assert AlphaVantageSource.lists_tables_without_credentials is True

    def test_get_schemas_returns_every_endpoint_as_full_refresh(self) -> None:
        schemas = AlphaVantageSource().get_schemas(_make_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Alpha Vantage has no server-side updated-at cursor, so nothing supports incremental.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

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

    def test_source_for_pipeline_plumbs_symbols_and_key(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "time_series_daily"
        inputs.logger = MagicMock()
        with patch(f"{MODULE}.alpha_vantage_source") as source_fn:
            AlphaVantageSource().source_for_pipeline(_make_config("abc", "ibm, aapl"), inputs)
        source_fn.assert_called_once()
        kwargs = source_fn.call_args.kwargs
        assert kwargs["api_key"] == "abc"
        # Symbols are parsed (upper-cased, de-duplicated) before handing off to the transport.
        assert kwargs["symbols"] == ["IBM", "AAPL"]
        assert kwargs["endpoint"] == "time_series_daily"

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

    @parameterized.expand(
        [
            ("quota", "Alpha Vantage API error [rate_limit_or_premium]"),
            ("unexpected", "Alpha Vantage API error [unexpected_response]"),
        ]
    )
    def test_non_retryable_errors_cover_permanent_failures(self, _name: str, expected_key: str) -> None:
        errors = AlphaVantageSource().get_non_retryable_errors()
        assert expected_key in errors
        assert errors[expected_key]

    def test_canonical_descriptions_keyed_by_endpoint(self) -> None:
        descriptions = AlphaVantageSource().get_canonical_descriptions()
        # Every documented entry must map to a real endpoint or the docs render orphaned tables.
        assert set(descriptions.keys()) <= set(ENDPOINTS)
        assert "time_series_daily" in descriptions
        assert "earnings" in descriptions
