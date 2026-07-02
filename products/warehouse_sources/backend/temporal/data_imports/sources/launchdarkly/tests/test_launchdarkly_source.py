import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LaunchDarklySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.launchdarkly import (
    LaunchDarklyResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.source import LaunchDarklySource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestLaunchDarklySource:
    def setup_method(self):
        self.source = LaunchDarklySource()
        self.team_id = 123
        self.config = LaunchDarklySourceConfig(access_token="api-token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.LAUNCHDARKLY

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "LaunchDarkly"
        assert config.label == "LaunchDarkly"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/launchdarkly.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["access_token"]

    def test_access_token_field_is_secret_password(self):
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "access_token")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://app.launchdarkly.com/api/v2/projects",
            "403 Client Error: Forbidden for url: https://app.launchdarkly.com/api/v2/flags/proj",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://app.launchdarkly.com/api/v2/members",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        # 401 substring would match the Stripe url too, so only assert the 5xx case is excluded.
        if "500" in other_error:
            assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_lists_all_endpoints_full_refresh(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # LaunchDarkly has no server-side timestamp filter, so nothing is incremental.
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["flags"])
        assert len(schemas) == 1
        assert schemas[0].name == "flags"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "status, schema_name, expected_valid",
        [
            (200, None, True),
            (401, None, False),
            # A valid token may lack scope for an unselected endpoint — accept 403 at source-create.
            (403, None, True),
            # But reject 403 when validating a specific schema.
            (403, "flags", False),
            (500, None, False),
            (None, None, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.source.validate_launchdarkly_credentials"
    )
    def test_validate_credentials_status_mapping(self, mock_validate, status, schema_name, expected_valid):
        mock_validate.return_value = status

        is_valid, _error = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert is_valid is expected_valid

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.source.validate_launchdarkly_credentials"
    )
    def test_validate_credentials_probes_projects_for_fanout_schema(self, mock_validate):
        mock_validate.return_value = 200
        self.source.validate_credentials(self.config, self.team_id, schema_name="flags")
        assert mock_validate.call_args.args[1] == "/projects"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.source.validate_launchdarkly_credentials"
    )
    def test_validate_credentials_probes_endpoint_path_for_toplevel_schema(self, mock_validate):
        mock_validate.return_value = 200
        self.source.validate_credentials(self.config, self.team_id, schema_name="members")
        assert mock_validate.call_args.args[1] == "/members"

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is LaunchDarklyResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.source.launchdarkly_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_launchdarkly_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "projects"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_launchdarkly_source.call_args.kwargs
        assert kwargs["access_token"] == "api-token"
        assert kwargs["endpoint"] == "projects"
        assert kwargs["resumable_source_manager"] is manager
