import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.healthchecks import (
    HealthchecksSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.healthchecks.source import HealthchecksSource


class TestHealthchecksSource:
    def setup_method(self):
        self.source = HealthchecksSource()
        self.team_id = 123
        self.config = HealthchecksSourceConfig(api_key="key", base_url=None)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.healthchecks.source.validate_healthchecks_credentials"
    )
    @mock.patch.object(HealthchecksSource, "is_database_host_valid")
    def test_validate_credentials_happy_path(self, mock_host_valid, mock_validate):
        mock_host_valid.return_value = (True, None)
        mock_validate.return_value = (True, None)

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_host_valid.assert_called_once_with("healthchecks.io", self.team_id)
        mock_validate.assert_called_once_with(None, "key")

    @mock.patch.object(HealthchecksSource, "is_database_host_valid")
    def test_validate_credentials_rejects_unsafe_host(self, mock_host_valid):
        mock_host_valid.return_value = (False, "Host is not allowed")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Host is not allowed"

    @mock.patch.object(HealthchecksSource, "is_database_host_valid")
    def test_validate_credentials_rejects_invalid_url(self, mock_host_valid):
        config = HealthchecksSourceConfig(api_key="key", base_url="ftp://nope")

        is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error_message == "Invalid Healthchecks base URL"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.healthchecks.source.is_cloud")
    @mock.patch.object(HealthchecksSource, "is_database_host_valid")
    def test_validate_credentials_rejects_http_on_cloud(self, mock_host_valid, mock_is_cloud):
        # On Cloud the required API key would travel in cleartext to a customer-supplied http:// host.
        mock_host_valid.return_value = (True, None)
        mock_is_cloud.return_value = True
        config = HealthchecksSourceConfig(api_key="key", base_url="http://hc.internal:8000")

        is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error_message == "Healthchecks base URL must use https"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.healthchecks.source.validate_healthchecks_credentials"
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.healthchecks.source.is_cloud")
    @mock.patch.object(HealthchecksSource, "is_database_host_valid")
    def test_validate_credentials_allows_http_when_self_hosted(self, mock_host_valid, mock_is_cloud, mock_validate):
        # Self-hosted deployments may reach their instance over http on their own network.
        mock_host_valid.return_value = (True, None)
        mock_is_cloud.return_value = False
        mock_validate.return_value = (True, None)
        config = HealthchecksSourceConfig(api_key="key", base_url="http://hc.internal:8000")

        is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is True
        assert error_message is None

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.healthchecks.source.healthchecks_source"
    )
    @mock.patch.object(HealthchecksSource, "is_database_host_valid")
    def test_source_for_pipeline_plumbs_arguments(self, mock_host_valid, mock_healthchecks_source):
        mock_host_valid.return_value = (True, None)
        inputs = mock.MagicMock()
        inputs.schema_name = "flips"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_healthchecks_source.call_args.kwargs
        assert kwargs["base_url"] is None
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "flips"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.healthchecks.source.healthchecks_source"
    )
    @mock.patch.object(HealthchecksSource, "is_database_host_valid")
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_host_valid, mock_healthchecks_source):
        mock_host_valid.return_value = (True, None)
        inputs = mock.MagicMock()
        inputs.schema_name = "checks"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1700000000

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_healthchecks_source.call_args.kwargs["db_incremental_field_last_value"] is None

    @mock.patch.object(HealthchecksSource, "is_database_host_valid")
    def test_source_for_pipeline_rejects_unsafe_host(self, mock_host_valid):
        mock_host_valid.return_value = (False, "Host is not allowed")
        inputs = mock.MagicMock()
        inputs.schema_name = "flips"
        inputs.team_id = self.team_id

        with pytest.raises(ValueError, match="Host is not allowed"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
