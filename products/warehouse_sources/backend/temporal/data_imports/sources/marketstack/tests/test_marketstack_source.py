from datetime import date
from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.marketstack import (
    MARKETSTACK_API_VERSION_V1,
    MARKETSTACK_API_VERSION_V2,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.source import MarketstackSource

_TIME_SERIES = {"eod", "intraday", "splits", "dividends"}
_REFERENCE = {"tickers", "exchanges", "currencies", "timezones"}


def _make_config(access_key: str = "key", symbols: str | None = "AAPL") -> Any:
    config = MagicMock()
    config.access_key = access_key
    config.symbols = symbols
    return config


class TestMarketstackSource:
    @parameterized.expand(
        [
            ("valid", True, True, None),
            ("invalid", False, False, "Invalid Marketstack access key"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, probe_result: bool, expected_ok: bool, expected_message: str | None
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.source.validate_marketstack_credentials",
            return_value=probe_result,
        ) as probe:
            ok, message = MarketstackSource().validate_credentials(_make_config(), team_id=1)
        assert ok is expected_ok
        assert message == expected_message
        # A pre-creation probe (no pin) resolves to the default version the new row is stamped with.
        assert probe.call_args.args[1] == MARKETSTACK_API_VERSION_V2

    def test_version_metadata_declares_v1_deprecation(self) -> None:
        source = MarketstackSource()
        assert source.supported_versions == (MARKETSTACK_API_VERSION_V1, MARKETSTACK_API_VERSION_V2)
        assert source.default_version == MARKETSTACK_API_VERSION_V2
        # The deprecated v1 carries the vendor's announced sunset date; the generic banner reads it.
        deprecation = source.get_version_deprecation(MARKETSTACK_API_VERSION_V1)
        assert deprecation is not None
        assert deprecation.sunset_at == date(2025, 6, 30)
        # The current default must never be flagged deprecated.
        assert source.get_version_deprecation(MARKETSTACK_API_VERSION_V2) is None

    @parameterized.expand(
        [
            ("http_unauthorized", "401 Client Error: Unauthorized for url: https://api.marketstack.com"),
            ("body_invalid_key", "Marketstack API error [invalid_access_key]"),
            ("body_usage_limit", "Marketstack API error [usage_limit_reached]"),
            ("body_function_restricted", "Marketstack API error [function_access_restricted]"),
            ("body_missing_symbols", "Marketstack API error [missing_symbols]"),
        ]
    )
    def test_non_retryable_errors_cover_permanent_failures(self, _name: str, expected_key: str) -> None:
        errors = MarketstackSource().get_non_retryable_errors()
        assert expected_key in errors
        assert errors[expected_key]
