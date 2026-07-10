import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import WindmillSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.windmill.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.windmill.source import WindmillSource
from products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill import WindmillResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

BASE_URL = "https://app.windmill.dev"
WORKSPACE = "my-workspace"


class TestWindmillSource:
    def setup_method(self):
        self.source = WindmillSource()
        self.team_id = 123
        self.config = WindmillSourceConfig(host=BASE_URL, workspace=WORKSPACE, api_token="token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.WINDMILL

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Windmill"
        assert config.label == "Windmill"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/windmill.svg"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["host", "workspace", "api_token"]

    def test_connection_host_fields_force_token_reentry_on_host_change(self):
        # host receives the api_token, so editing it must re-require the token (no exfiltration
        # of the stored bearer token to an attacker-controlled host).
        assert self.source.connection_host_fields == ["host"]

    def test_api_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://app.windmill.dev/api/w/my-workspace/scripts/list",
            "403 Client Error: Forbidden for url: https://app.windmill.dev/api/w/my-workspace/audit/list",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        ["500 Server Error", "429 Client Error: Too Many Requests"],
    )
    def test_non_retryable_errors_does_not_match_transient(self, other_error):
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only completed_jobs exposes a genuine server-side timestamp filter.
        assert incremental == {"completed_jobs"}

    def test_completed_jobs_advertises_both_cursor_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["completed_jobs"].incremental_fields == INCREMENTAL_FIELDS["completed_jobs"]
        assert {f["field"] for f in schemas["completed_jobs"].incremental_fields} == {"created_at", "started_at"}
        assert schemas["scripts"].incremental_fields == []
        assert schemas["scripts"].supports_append is False

    def test_audit_logs_off_by_default(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        # Audit logs are EE-only and admin-gated, so they must not be selected by default.
        assert schemas["audit_logs"].should_sync_default is False
        assert schemas["completed_jobs"].should_sync_default is True

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["scripts"])
        assert [s.name for s in schemas] == ["scripts"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return",
        [(True, None), (False, "Invalid Windmill API token")],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.windmill.source.validate_windmill_credentials"
    )
    def test_validate_credentials_plumbs_arguments(self, mock_validate, mock_return):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id)

        assert result == mock_return
        mock_validate.assert_called_once_with("token", BASE_URL, WORKSPACE, self.team_id)

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is WindmillResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.windmill.source.windmill_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_windmill_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "completed_jobs"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "created_at"
        inputs.team_id = 777

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_windmill_source.call_args.kwargs
        assert kwargs["api_token"] == "token"
        assert kwargs["base_url"] == BASE_URL
        assert kwargs["workspace"] == WORKSPACE
        assert kwargs["endpoint"] == "completed_jobs"
        assert kwargs["team_id"] == 777
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert kwargs["incremental_field"] == "created_at"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.windmill.source.windmill_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_windmill_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "scripts"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_windmill_source.call_args.kwargs["db_incremental_field_last_value"] is None
