import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.exchange_rates_api import (
    ExchangeRatesApiResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.source import (
    ExchangeRatesApiSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    ExchangeRatesApiSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestExchangeRatesApiSource:
    def setup_method(self) -> None:
        self.source = ExchangeRatesApiSource()
        self.team_id = 123
        self.config = ExchangeRatesApiSourceConfig(access_key="era-test", base_currency="EUR", start_date=None)

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.EXCHANGERATESAPI

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "ExchangeRatesApi"
        assert config.label == "Exchange Rates API"
        assert config.category == DataWarehouseSourceCategory.FINANCE___ACCOUNTING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Kept behind the unreleased flag until the source has been exercised end to end.
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/exchange-rates-api"
        assert [f.name for f in config.fields] == ["access_key", "base_currency", "start_date"]

    def test_access_key_field_is_secret_password(self) -> None:
        field = next(f for f in self.source.get_source_config.fields if f.name == "access_key")
        assert isinstance(field, SourceFieldInputConfig)
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    @pytest.mark.parametrize("field_name", ["base_currency", "start_date"])
    def test_optional_fields_are_not_required(self, field_name: str) -> None:
        field = next(f for f in self.source.get_source_config.fields if f.name == field_name)
        assert isinstance(field, SourceFieldInputConfig)
        assert field.required is False
        assert field.secret is False

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — safe to surface in public docs.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.exchangeratesapi.io/v1/symbols?access_key=x",
            "403 Client Error: Forbidden for url: https://api.exchangeratesapi.io/v1/timeseries?access_key=x",
        ],
    )
    def test_non_retryable_errors_match_auth_and_plan_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.exchangeratesapi.io/v1/latest",
            "500 Server Error for url: https://api.exchangeratesapi.io/v1/timeseries",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient(self, other_error: str) -> None:
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_only_timeseries_supports_incremental(self) -> None:
        by_name = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        # Only /timeseries exposes a server-side start_date filter.
        assert by_name["timeseries"].supports_incremental is True
        assert [f["field"] for f in by_name["timeseries"].incremental_fields] == ["date"]
        assert by_name["symbols"].supports_incremental is False
        assert by_name["latest"].supports_incremental is False

    def test_timeseries_off_by_default(self) -> None:
        by_name = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        # Opt-in to avoid surprising free-tier request usage on a multi-year backfill.
        assert by_name["timeseries"].should_sync_default is False
        assert by_name["symbols"].should_sync_default is True

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["latest"])
        assert len(schemas) == 1
        assert schemas[0].name == "latest"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (
                False,
                False,
                "Unable to verify your Exchange Rates API access key. Check that the key is correct and that exchangeratesapi.io is reachable.",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.source.validate_exchange_rates_api_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: mock.MagicMock, mock_return: bool, expected_valid: bool, expected_message: str | None
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("era-test")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ExchangeRatesApiResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.source.exchange_rates_api_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "timeseries"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["access_key"] == "era-test"
        assert kwargs["endpoint"] == "timeseries"
        assert kwargs["base_currency"] == "EUR"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.source.exchange_rates_api_source"
    )
    def test_source_for_pipeline_drops_watermark_when_not_incremental(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "latest"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        # A non-incremental sync must not pass a stale watermark down to the transport.
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_all_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)
        assert "rate" in descriptions["timeseries"]["columns"]
