from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.qualaroo import (
    QualarooSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualaroo.source import QualarooSource


class TestQualarooSource:
    def setup_method(self) -> None:
        self.source = QualarooSource()
        self.team_id = 123
        self.config = QualarooSourceConfig(api_key="q-key", api_secret="q-secret")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.qualaroo.source._validate_qualaroo_credentials"
    )
    def test_validate_credentials_delegates_to_qualaroo(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-result mapping lives in qualaroo.validate_credentials; the source only forwards
        # the account-wide key/secret and returns the result unchanged.
        mock_validate.return_value = (False, "Invalid Qualaroo API key or secret")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("q-key", "q-secret")
        assert result == (False, "Invalid Qualaroo API key or secret")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.qualaroo.source.qualaroo_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "nudges"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "q-key"
        assert kwargs["api_secret"] == "q-secret"
        assert kwargs["endpoint"] == "nudges"
        assert kwargs["resumable_source_manager"] is manager
