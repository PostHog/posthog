from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.alpha_vantage.source import AlphaVantageSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.alpha_vantage.source"


def _make_config(api_key: str = "key", symbols: str = "IBM, AAPL") -> Any:
    config = MagicMock()
    config.api_key = api_key
    config.symbols = symbols
    return config


class TestAlphaVantageSource:
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
