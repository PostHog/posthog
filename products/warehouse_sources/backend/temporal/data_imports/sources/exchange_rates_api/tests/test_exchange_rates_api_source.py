import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.source import (
    ExchangeRatesApiSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.exchangeratesapi import (
    ExchangeRatesApiSourceConfig,
)


class TestExchangeRatesApiSource:
    def setup_method(self) -> None:
        self.source = ExchangeRatesApiSource()
        self.team_id = 123
        self.config = ExchangeRatesApiSourceConfig(access_key="era-test", base_currency="EUR", start_date=None)

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — safe to surface in public docs.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["latest"])
        assert len(schemas) == 1
        assert schemas[0].name == "latest"

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
