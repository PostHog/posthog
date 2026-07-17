import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import WrikeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.wrike.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.wrike.source import WrikeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.wrike.wrike import WrikeResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestWrikeSource:
    def setup_method(self):
        self.source = WrikeSource()
        self.team_id = 123
        self.config = WrikeSourceConfig(access_token="token", host="www.wrike.com")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.WRIKE

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Wrike"
        assert config.label == "Wrike"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/wrike.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["access_token", "host"]

    def test_access_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "access_token"
        )
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    def test_host_field_is_plain_required_text(self):
        config = self.source.get_source_config
        host_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "host")
        assert host_field.type == SourceFieldInputConfigType.TEXT
        assert host_field.secret is False
        assert host_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://www.wrike.com/api/v4/tasks",
            "403 Client Error: Forbidden for url: https://www.wrike.com/api/v4/contacts",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://www.wrike.com/api/v4/tasks",
            "500 Server Error for url: https://www.wrike.com/api/v4/tasks",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_covers_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_get_schemas_are_full_refresh_only(self):
        # Wrike ships full refresh only until the server-side updatedDate filter is verified.
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["tasks"])
        assert len(schemas) == 1
        assert schemas[0].name == "tasks"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return",
        [
            (True, None),
            (False, "Invalid Wrike access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.wrike.source.validate_wrike_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert (is_valid, error_message) == mock_return
        mock_validate.assert_called_once_with(self.config.access_token, self.config.host)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is WrikeResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.wrike.source.wrike_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_wrike_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "tasks"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_wrike_source.assert_called_once()
        kwargs = mock_wrike_source.call_args.kwargs
        assert kwargs["access_token"] == "token"
        assert kwargs["host"] == "www.wrike.com"
        assert kwargs["endpoint"] == "tasks"
        assert kwargs["resumable_source_manager"] is manager
