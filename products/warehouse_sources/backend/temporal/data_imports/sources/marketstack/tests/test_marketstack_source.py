from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.marketstack import (
    MarketstackResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.source import MarketstackSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_TIME_SERIES = {"eod", "intraday", "splits", "dividends"}
_REFERENCE = {"tickers", "exchanges", "currencies", "timezones"}


def _make_config(access_key: str = "key", symbols: str | None = "AAPL") -> Any:
    config = MagicMock()
    config.access_key = access_key
    config.symbols = symbols
    return config


class TestMarketstackSource:
    def test_source_type(self) -> None:
        assert MarketstackSource().source_type == ExternalDataSourceType.MARKETSTACK

    def test_source_config_fields(self) -> None:
        config = MarketstackSource().get_source_config
        assert [f.name for f in config.fields] == ["access_key", "symbols"]

        access_key_field = config.fields[0]
        assert isinstance(access_key_field, SourceFieldInputConfig)
        # The access key is a secret credential, so it must render as a password input.
        assert access_key_field.type == "password"
        assert access_key_field.secret is True
        assert access_key_field.required is True

        symbols_field = config.fields[1]
        assert isinstance(symbols_field, SourceFieldInputConfig)
        # Symbols are only needed for the time-series tables, so the field is optional.
        assert symbols_field.required is False
        assert symbols_field.secret is False

    def test_source_config_stays_unreleased_alpha(self) -> None:
        config = MarketstackSource().get_source_config
        assert config.unreleasedSource is True
        assert config.releaseStatus == "alpha"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/marketstack"

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = MarketstackSource().get_schemas(_make_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_marks_only_time_series_incremental(self) -> None:
        schemas = {s.name: s for s in MarketstackSource().get_schemas(_make_config(), team_id=1)}
        for name in _TIME_SERIES:
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert [f["field"] for f in schemas[name].incremental_fields] == ["date"]
        for name in _REFERENCE:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

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
        ):
            ok, message = MarketstackSource().validate_credentials(_make_config(), team_id=1)
        assert ok is expected_ok
        assert message == expected_message

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = MarketstackSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is MarketstackResumeConfig

    def test_source_for_pipeline_plumbs_symbols_and_keys(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "eod"
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2021-04-09"

        response = MarketstackSource().source_for_pipeline(_make_config("abc", "AAPL,MSFT"), MagicMock(), inputs)

        assert response.name == "eod"
        assert response.primary_keys == ["symbol", "exchange", "date"]

    def test_source_for_pipeline_drops_watermark_when_not_incremental(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "tickers"
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "should-be-ignored"

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.source.marketstack_source"
        ) as mocked:
            MarketstackSource().source_for_pipeline(_make_config(), MagicMock(), inputs)
        # A full-refresh run must never forward a stale watermark to the transport.
        assert mocked.call_args.kwargs["db_incremental_field_last_value"] is None

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

    def test_canonical_descriptions_keyed_by_endpoint(self) -> None:
        descriptions = MarketstackSource().get_canonical_descriptions()
        # Every documented entry must map to a real endpoint or the docs render orphaned tables.
        assert set(descriptions.keys()) <= set(ENDPOINTS)
        assert "eod" in descriptions
        assert "tickers" in descriptions
