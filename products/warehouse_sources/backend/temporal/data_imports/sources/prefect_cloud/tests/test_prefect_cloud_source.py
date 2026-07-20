import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PrefectCloudSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.prefect_cloud import (
    PrefectCloudResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.settings import (
    ENDPOINTS,
    PREFECT_CLOUD_ENDPOINTS,
    RUN_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.source import PrefectCloudSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Endpoints whose Prefect filter model exposes a server-side `after_` time filter with an
# ascending sort; everything else is full refresh only.
_INCREMENTAL_ENDPOINTS = {"flow_runs", "task_runs"}
_FULL_REFRESH_ENDPOINTS = {"flows", "deployments", "work_pools", "work_queues"}

_ACCOUNT_ID = "11111111-2222-3333-4444-555555555555"
_WORKSPACE_ID = "66666666-7777-8888-9999-aaaaaaaaaaaa"


class TestPrefectCloudSource:
    def setup_method(self):
        self.source = PrefectCloudSource()
        self.team_id = 123
        self.config = PrefectCloudSourceConfig(account_id=_ACCOUNT_ID, workspace_id=_WORKSPACE_ID, api_key="pnu_key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.PREFECTCLOUD

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "PrefectCloud"
        assert config.label == "Prefect Cloud"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/prefect_cloud.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/prefect-cloud"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["account_id", "workspace_id", "api_key"]

    def test_connection_host_fields_force_secret_reentry_on_workspace_change(self):
        # Both IDs retarget the stored API key, so changing either must require re-entering it.
        assert self.source.connection_host_fields == ["account_id", "workspace_id"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.prefect.cloud/api/accounts/x/workspaces/y/flow_runs/filter",
            "403 Client Error: Forbidden for url: https://api.prefect.cloud/api/accounts/x/workspaces/y/task_runs/filter",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.prefect.cloud/api/accounts/x/workspaces/y/flow_runs/filter",
            "500 Server Error: Internal Server Error for url: https://api.prefect.cloud/api/accounts/x/workspaces/y/flows/filter",
            "HTTPSConnectionPool(host='api.prefect.cloud', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_match_endpoints_with_correct_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name in _INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert [f["field"] for f in schemas[name].incremental_fields] == list(
                PREFECT_CLOUD_ENDPOINTS[name].incremental_sorts
            )
            # Losing the trailing re-read window silently freezes run states at first import.
            assert schemas[name].default_incremental_lookback_seconds == RUN_LOOKBACK_SECONDS
        for name in _FULL_REFRESH_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["flow_runs"])
        assert len(schemas) == 1
        assert schemas[0].name == "flow_runs"

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(PREFECT_CLOUD_ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Prefect Cloud API key"),
            (
                (False, 404),
                False,
                "Prefect Cloud account or workspace not found — check the account ID and workspace ID",
            ),
            (
                (False, None),
                False,
                "Could not connect to Prefect Cloud with the provided account ID, workspace ID, and API key",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.source.validate_prefect_cloud_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(_ACCOUNT_ID, _WORKSPACE_ID, "pnu_key")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.source.validate_prefect_cloud_credentials"
    )
    def test_validate_credentials_surfaces_malformed_ids(self, mock_validate):
        mock_validate.side_effect = ValueError("Invalid Prefect Cloud account ID: 'not-a-uuid'.")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "Invalid Prefect Cloud account ID" in (error_message or "")

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is PrefectCloudResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.source.prefect_cloud_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_prefect_cloud_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "flow_runs"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "start_time"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_prefect_cloud_source.assert_called_once()
        kwargs = mock_prefect_cloud_source.call_args.kwargs
        assert kwargs["account_id"] == _ACCOUNT_ID
        assert kwargs["workspace_id"] == _WORKSPACE_ID
        assert kwargs["api_key"] == "pnu_key"
        assert kwargs["endpoint"] == "flow_runs"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert kwargs["incremental_field"] == "start_time"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.source.prefect_cloud_source"
    )
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_prefect_cloud_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "flows"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_prefect_cloud_source.call_args.kwargs["db_incremental_field_last_value"] is None
