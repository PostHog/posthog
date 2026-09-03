import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openexchangerates import (
    OpenExchangeRatesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.source import (
    OpenExchangeRatesSource,
)


class TestOpenExchangeRatesSource:
    def setup_method(self) -> None:
        self.source = OpenExchangeRatesSource()
        self.team_id = 123
        self.config = OpenExchangeRatesSourceConfig(app_id="oxr-test", base_currency="USD", start_date=None)

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — safe to surface in public docs.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://openexchangerates.org/api/latest.json",
            "403 Client Error: Forbidden for url: https://openexchangerates.org/api/usage.json",
            "429 Client Error: Too Many Requests for url: https://openexchangerates.org/api/latest.json?base=EUR",
        ],
    )
    def test_non_retryable_errors_match_auth_and_plan_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error for url: https://openexchangerates.org/api/historical/2024-01-01.json",
            "503 Server Error for url: https://openexchangerates.org/api/latest.json",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient(self, other_error: str) -> None:
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_only_historical_supports_incremental(self) -> None:
        by_name = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        # Only /historical selects a single value date server-side, so only new days are fetched.
        assert by_name["historical"].supports_incremental is True
        assert [f["field"] for f in by_name["historical"].incremental_fields] == ["date"]
        assert by_name["currencies"].supports_incremental is False
        assert by_name["latest"].supports_incremental is False
        assert by_name["usage"].supports_incremental is False

    def test_all_endpoints_sync_by_default(self) -> None:
        by_name = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        assert all(schema.should_sync_default for schema in by_name.values())

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
                "Unable to verify your Open Exchange Rates App ID. Check that the App ID is correct and that openexchangerates.org is reachable.",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.source.validate_open_exchange_rates_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: mock.MagicMock, mock_return: bool, expected_valid: bool, expected_message: str | None
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("oxr-test")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.source.open_exchange_rates_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "historical"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["app_id"] == "oxr-test"
        assert kwargs["endpoint"] == "historical"
        assert kwargs["base_currency"] == "USD"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.source.open_exchange_rates_source"
    )
    def test_source_for_pipeline_drops_watermark_when_not_incremental(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "latest"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        # A non-incremental sync must not pass a stale watermark down to the transport.
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
