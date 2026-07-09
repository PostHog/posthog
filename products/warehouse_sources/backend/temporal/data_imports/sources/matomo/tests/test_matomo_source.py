import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MatomoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.matomo.matomo import MatomoResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.matomo.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.matomo.source import MatomoSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestMatomoSource:
    def setup_method(self):
        self.source = MatomoSource()
        self.team_id = 123
        self.config = MatomoSourceConfig(host="https://myorg.matomo.cloud", site_id="1", api_token="token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.MATOMO

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Matomo"
        assert config.label == "Matomo"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/matomo.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["host", "site_id", "api_token"]

    def test_api_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    def test_connection_host_fields_cover_host(self):
        # The instance URL decides where the stored token gets sent.
        assert self.source.connection_host_fields == ["host"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://myorg.matomo.cloud/index.php",
            "403 Client Error: Forbidden for url: https://myorg.matomo.cloud/index.php",
            "Matomo API error: You can't access this resource",
        ],
    )
    def test_non_retryable_errors_match_known_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_server_errors(self):
        non_retryable_errors = self.source.get_non_retryable_errors()
        error = "500 Server Error for url: https://myorg.matomo.cloud/index.php"
        assert not any(key in error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # Everything is incremental: visits via minTimestamp, reports via the
        # injected per-day _date.
        assert all(schema.supports_incremental for schema in schemas.values())
        assert [f["field"] for f in schemas["visits"].incremental_fields] == ["serverTimestamp"]
        assert [f["field"] for f in schemas["referrers"].incremental_fields] == ["_date"]
        assert schemas["visits"].incremental_fields == INCREMENTAL_FIELDS["visits"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["visits"])
        assert len(schemas) == 1
        assert schemas[0].name == "visits"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

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

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is MatomoResumeConfig

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
