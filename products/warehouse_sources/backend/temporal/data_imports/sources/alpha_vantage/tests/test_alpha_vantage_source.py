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
    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs can render tables.
        assert AlphaVantageSource.lists_tables_without_credentials is True

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
