import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.payfit import PayFitSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.payfit.source import PayFitSource


class TestPayFitSource:
    def setup_method(self) -> None:
        self.source = PayFitSource()
        self.team_id = 123
        self.config = PayFitSourceConfig(api_key="payfit-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.payfit.source.validate_credentials")
    def test_validate_credentials_probes_token_at_source_create(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-message mapping lives in payfit.validate_credentials; here we only assert the
        # source probes with the configured key and returns the delegate's verdict unchanged.
        mock_validate.return_value = (False, "Invalid PayFit API key")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("payfit-key")
        assert result == (False, "Invalid PayFit API key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.payfit.source.check_schema_access")
    def test_validate_credentials_probes_endpoint_scope_for_schema(self, mock_check: mock.MagicMock) -> None:
        # PayFit keys carry per-endpoint scopes, so per-schema validation must probe that endpoint
        # rather than only introspecting the token.
        mock_check.return_value = (True, None)
        result = self.source.validate_credentials(self.config, self.team_id, schema_name="absences")
        mock_check.assert_called_once_with("payfit-key", "absences")
        assert result == (True, None)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.payfit.source.validate_credentials")
    def test_validate_credentials_falls_back_for_unknown_schema(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        result = self.source.validate_credentials(self.config, self.team_id, schema_name="not_a_table")
        mock_validate.assert_called_once_with("payfit-key")
        assert result == (True, None)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.payfit.source.payfit_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "collaborators"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "payfit-key"
        assert kwargs["endpoint"] == "collaborators"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown PayFit schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
