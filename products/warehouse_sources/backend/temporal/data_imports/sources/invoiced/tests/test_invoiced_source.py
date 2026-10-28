from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.invoiced import (
    InvoicedSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiced.source import InvoicedSource


class TestInvoicedSource:
    def setup_method(self) -> None:
        self.source = InvoicedSource()
        self.team_id = 123
        self.config = InvoicedSourceConfig(api_key="invoiced-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.invoiced.source.validate_credentials")
    def test_validate_credentials_delegates_with_api_key(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-message mapping lives in invoiced.validate_credentials; here we only assert
        # the source probes with the configured key and returns the delegate's verdict unchanged.
        mock_validate.return_value = (False, "Invalid Invoiced API key")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("invoiced-key")
        assert result == (False, "Invalid Invoiced API key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.invoiced.source.invoiced_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "invoices"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "invoiced-key"
        assert kwargs["endpoint"] == "invoices"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000

    def test_source_for_pipeline_drops_cursor_on_full_refresh(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            "customers",
            [ScriptedResponse(json=[])],
            should_use_incremental_field=False,
            db_incremental_field_last_value=1700000000,
        )

        assert result.raised is None
        assert result.requests[0].param("updated_after") is None
