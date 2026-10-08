from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.marketstack import (
    MARKETSTACK_API_VERSION_V1,
    MARKETSTACK_API_VERSION_V2,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.source import MarketstackSource


def _make_config(access_key: str = "key", symbols: str | None = "AAPL") -> Any:
    config = MagicMock()
    config.access_key = access_key
    config.symbols = symbols
    return config


class TestMarketstackSource:
    def test_get_schemas_filters_by_names(self) -> None:
        schemas = MarketstackSource().get_schemas(_make_config(), team_id=1, names=["eod", "exchanges"])
        assert {s.name for s in schemas} == {"eod", "exchanges"}

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

    def test_source_for_pipeline_plumbs_symbols_and_keys(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "eod"
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2021-04-09"
        inputs.api_version = MARKETSTACK_API_VERSION_V2

        response = MarketstackSource().source_for_pipeline(_make_config("abc", "AAPL,MSFT"), MagicMock(), inputs)

        assert response.name == "eod"
        assert response.primary_keys == ["symbol", "exchange", "date"]

    @parameterized.expand(
        [
            ("no_pin_resolves_to_default", None, MARKETSTACK_API_VERSION_V2),
            ("legacy_pin_honored", MARKETSTACK_API_VERSION_V1, MARKETSTACK_API_VERSION_V1),
            ("new_pin_honored", MARKETSTACK_API_VERSION_V2, MARKETSTACK_API_VERSION_V2),
        ]
    )
    def test_source_for_pipeline_threads_resolved_version(self, _name: str, pin: str | None, expected: str) -> None:
        inputs = MagicMock()
        inputs.schema_name = "eod"
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = False
        inputs.api_version = pin

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.source.marketstack_source"
        ) as mocked:
            MarketstackSource().source_for_pipeline(_make_config(), MagicMock(), inputs)
        assert mocked.call_args.kwargs["api_version"] == expected

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
