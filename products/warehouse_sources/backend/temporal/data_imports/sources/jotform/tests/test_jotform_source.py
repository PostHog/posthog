import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.jotform import (
    JotformSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source import JotformSource


class TestJotformSource:
    def setup_method(self):
        self.source = JotformSource()
        self.team_id = 123
        self.config = JotformSourceConfig(api_key="key-123", region="us")

    def test_only_forms_and_submissions_are_incremental(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        incremental = {name for name, s in schemas.items() if s.supports_incremental}
        assert incremental == {"forms", "submissions"}

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Jotform API key, region, or Enterprise domain"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source.validate_jotform_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, self.config.region, None)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source._is_host_safe")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source.validate_jotform_credentials"
    )
    def test_validate_credentials_rejects_unsafe_enterprise_host(self, mock_validate, mock_host_safe):
        mock_host_safe.return_value = (False, "Hosts with internal IP addresses are not allowed")
        config = JotformSourceConfig(api_key="key", region="us", enterprise_domain="https://10.0.0.1/")

        is_valid, error = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error == "Hosts with internal IP addresses are not allowed"
        # An unsafe host must short-circuit before we ever send the key to it.
        mock_validate.assert_not_called()
        mock_host_safe.assert_called_once_with("10.0.0.1", self.team_id)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source._is_host_safe")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source.validate_jotform_credentials"
    )
    def test_validate_credentials_skips_host_check_without_enterprise_domain(self, mock_validate, mock_host_safe):
        mock_validate.return_value = True

        self.source.validate_credentials(self.config, self.team_id)

        mock_host_safe.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source._is_host_safe",
        return_value=(True, None),
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source.jotform_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_jotform_source, mock_host_safe):
        inputs = mock.MagicMock()
        inputs.schema_name = "submissions"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01 00:00:00"
        inputs.incremental_field = "created_at"
        config = JotformSourceConfig(api_key="key-123", region="eu", enterprise_domain="forms.acme.com")
        manager = mock.MagicMock()

        self.source.source_for_pipeline(config, manager, inputs)

        kwargs = mock_jotform_source.call_args.kwargs
        assert kwargs["api_key"] == "key-123"
        assert kwargs["region"] == "eu"
        assert kwargs["enterprise_domain"] == "forms.acme.com"
        assert kwargs["endpoint"] == "submissions"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01 00:00:00"
        assert kwargs["incremental_field"] == "created_at"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source.jotform_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_jotform_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "reports"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01 00:00:00"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_jotform_source.call_args.kwargs["db_incremental_field_last_value"] is None

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source._is_host_safe")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source.jotform_source")
    def test_source_for_pipeline_rejects_unsafe_enterprise_host(self, mock_jotform_source, mock_host_safe):
        # DNS can be repointed at an internal host after setup, so the host is re-checked before each
        # sync — not just at validation.
        mock_host_safe.return_value = (False, "Hosts with internal IP addresses are not allowed")
        config = JotformSourceConfig(api_key="key", region="us", enterprise_domain="https://10.0.0.1/")
        inputs = mock.MagicMock()

        with pytest.raises(ValueError, match="Hosts with internal IP addresses are not allowed"):
            self.source.source_for_pipeline(config, mock.MagicMock(), inputs)

        mock_jotform_source.assert_not_called()
        mock_host_safe.assert_called_once_with("10.0.0.1", inputs.team_id)
