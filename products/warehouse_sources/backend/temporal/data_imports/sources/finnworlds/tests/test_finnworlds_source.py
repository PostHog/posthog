from typing import Any

import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.finnworlds import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.finnworlds.finnworlds import MAX_TICKERS
from products.warehouse_sources.backend.temporal.data_imports.sources.finnworlds.settings import (
    ENDPOINTS,
    FINNWORLDS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.finnworlds.source import FinnworldsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FinnworldsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> mock.MagicMock:
    inputs = mock.MagicMock()
    inputs.schema_name = overrides.get("schema_name", "dividends")
    inputs.logger = overrides.get("logger", mock.MagicMock())
    return inputs


class TestFinnworldsSource:
    def setup_method(self) -> None:
        self.source = FinnworldsSource()
        self.team_id = 123
        self.config = FinnworldsSourceConfig(api_key="fw-test", tickers="AAPL, MSFT")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.FINNWORLDS

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Finnworlds"
        assert config.label == "Finnworlds"
        assert config.category == DataWarehouseSourceCategory.FINANCE___ACCOUNTING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/finnworlds"

        field_names = [f.name for f in config.fields]
        assert field_names == ["api_key", "tickers"]

        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

        tickers_field = config.fields[1]
        assert isinstance(tickers_field, SourceFieldInputConfig)
        assert tickers_field.type == SourceFieldInputConfigType.TEXTAREA
        assert tickers_field.required is True
        assert tickers_field.secret is False

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_matches_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", sorted(FINNWORLDS_ENDPOINTS))
    def test_all_schemas_full_refresh_only(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []

    def test_get_schemas_respects_should_sync_default(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        # Bond yields fan out globally and are heavier, so they're off by default.
        assert schemas["bond_yields"].should_sync_default is False
        assert schemas["dividends"].should_sync_default is True

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["dividends"])
        assert [s.name for s in schemas] == ["dividends"]

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_without_credentials(self) -> None:
        # lists_tables_without_credentials=True + static catalog → public docs can list tables.
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    def test_validate_credentials_success(self) -> None:
        with mock.patch.object(source_module, "validate_finnworlds_credentials", return_value=(True, None)):
            assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

    def test_validate_credentials_failure(self) -> None:
        with mock.patch.object(
            source_module, "validate_finnworlds_credentials", return_value=(False, "Invalid Finnworlds API key")
        ):
            ok, message = self.source.validate_credentials(self.config, self.team_id)
        assert ok is False
        assert message is not None

    def test_validate_credentials_rejects_oversized_ticker_list(self) -> None:
        # Too many tickers is rejected at setup without ever probing the API, bounding outbound fan-out.
        config = FinnworldsSourceConfig(api_key="fw-test", tickers=",".join(f"T{i}" for i in range(MAX_TICKERS + 1)))
        with mock.patch.object(source_module, "validate_finnworlds_credentials") as probe:
            ok, message = self.source.validate_credentials(config, self.team_id)
        assert ok is False
        assert message is not None
        assert "Too many tickers" in message
        probe.assert_not_called()

    def test_get_non_retryable_errors_includes_auth(self) -> None:
        errors = self.source.get_non_retryable_errors()
        assert "Finnworlds authentication failed" in errors

    def test_get_canonical_descriptions_keyed_by_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions).issubset(set(ENDPOINTS))
        assert "income_statements" in descriptions

    def test_source_for_pipeline_plumbs_parsed_tickers(self) -> None:
        inputs = _make_inputs(schema_name="dividends")
        with mock.patch.object(source_module, "finnworlds_source") as mocked:
            self.source.source_for_pipeline(self.config, inputs)

        mocked.assert_called_once()
        _, kwargs = mocked.call_args
        assert kwargs["api_key"] == "fw-test"
        assert kwargs["endpoint"] == "dividends"
        assert kwargs["tickers"] == ["AAPL", "MSFT"]
        assert kwargs["logger"] is inputs.logger
