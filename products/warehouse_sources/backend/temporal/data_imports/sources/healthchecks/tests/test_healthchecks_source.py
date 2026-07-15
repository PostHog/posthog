import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HealthchecksSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.healthchecks.healthchecks import (
    HealthchecksResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.healthchecks.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.healthchecks.source import HealthchecksSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestHealthchecksSource:
    def setup_method(self):
        self.source = HealthchecksSource()
        self.team_id = 123
        self.config = HealthchecksSourceConfig(api_key="key", base_url=None)

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.HEALTHCHECKS

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Healthchecks"
        assert config.label == "Healthchecks.io"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/healthchecks"

        field_names = [f.name for f in config.fields]
        assert field_names == ["api_key", "base_url"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    def test_base_url_field_is_optional_text(self):
        config = self.source.get_source_config
        base_url_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "base_url"
        )
        assert base_url_field.type == SourceFieldInputConfigType.TEXT
        assert base_url_field.required is False
        assert base_url_field.secret is False

    def test_connection_host_fields_cover_base_url(self):
        # The base URL decides where the stored API key gets sent.
        assert self.source.connection_host_fields == ["base_url"]

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog with no I/O, so the public docs table list can render.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://healthchecks.io/api/v3/checks/",
        ],
    )
    def test_non_retryable_errors_match_known_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_ignore_server_errors(self):
        non_retryable_errors = self.source.get_non_retryable_errors()
        error = "500 Server Error for url: https://healthchecks.io/api/v3/checks/"
        assert not any(key in error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # Only flips exposes a genuine server-side timestamp filter (start=), so only it is incremental.
        assert schemas["flips"].supports_incremental is True
        assert schemas["checks"].supports_incremental is False
        assert schemas["channels"].supports_incremental is False
        assert schemas["pings"].supports_incremental is False
        assert [f["field"] for f in schemas["flips"].incremental_fields] == ["timestamp"]
        assert schemas["flips"].incremental_fields == INCREMENTAL_FIELDS["flips"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["flips"])
        assert len(schemas) == 1
        assert schemas[0].name == "flips"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self):
        tables = self.source.get_documented_tables()
        by_name = {t["name"]: t for t in tables}
        assert set(by_name) == set(ENDPOINTS)
        # flips advertises Incremental; checks is full refresh only.
        assert "Incremental" in by_name["flips"]["sync_methods"]
        assert by_name["checks"]["sync_methods"] == ["Full refresh"]

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

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is HealthchecksResumeConfig

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
