import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.matomo import MatomoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.matomo.source import MatomoSource


class TestMatomoSource:
    def setup_method(self):
        self.source = MatomoSource()
        self.team_id = 123
        self.config = MatomoSourceConfig(host="https://myorg.matomo.cloud", site_id="1", api_token="token")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.matomo.source.validate_matomo_credentials"
    )
    @mock.patch.object(MatomoSource, "is_database_host_valid")
    def test_validate_credentials_happy_path(self, mock_host_valid, mock_validate):
        mock_host_valid.return_value = (True, None)
        mock_validate.return_value = True

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_host_valid.assert_called_once_with("myorg.matomo.cloud", self.team_id)
        mock_validate.assert_called_once_with("https://myorg.matomo.cloud", "1", "token")

    @mock.patch.object(MatomoSource, "is_database_host_valid")
    def test_validate_credentials_rejects_unsafe_host(self, mock_host_valid):
        mock_host_valid.return_value = (False, "Host is not allowed")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Host is not allowed"

    def test_validate_credentials_rejects_invalid_url(self):
        config = MatomoSourceConfig(host="ftp://nope", site_id="1", api_token="token")

        is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error_message == "Invalid Matomo instance URL"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.matomo.source.validate_matomo_credentials"
    )
    @mock.patch.object(MatomoSource, "is_database_host_valid")
    def test_validate_credentials_bad_token(self, mock_host_valid, mock_validate):
        mock_host_valid.return_value = (True, None)
        mock_validate.return_value = False

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "Invalid Matomo credentials" in (error_message or "")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.matomo.source.matomo_source")
    @mock.patch.object(MatomoSource, "is_database_host_valid")
    def test_source_for_pipeline_plumbs_arguments(self, mock_host_valid, mock_matomo_source):
        mock_host_valid.return_value = (True, None)
        inputs = mock.MagicMock()
        inputs.schema_name = "visits"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_matomo_source.assert_called_once()
        kwargs = mock_matomo_source.call_args.kwargs
        assert kwargs["host"] == "https://myorg.matomo.cloud"
        assert kwargs["site_id"] == "1"
        assert kwargs["api_token"] == "token"
        assert kwargs["endpoint"] == "visits"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000

    @mock.patch.object(MatomoSource, "is_database_host_valid")
    def test_source_for_pipeline_rejects_unsafe_host(self, mock_host_valid):
        mock_host_valid.return_value = (False, "Host is not allowed")
        inputs = mock.MagicMock()
        inputs.schema_name = "visits"
        inputs.team_id = self.team_id

        with pytest.raises(ValueError, match="Host is not allowed"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
