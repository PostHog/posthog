import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pluralsightflow import (
    PluralsightFlowSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pluralsight_flow.pluralsight_flow import (
    PluralsightFlowResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pluralsight_flow.settings import (
    CORE_ENDPOINTS,
    ENDPOINTS,
    METRIC_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pluralsight_flow.source import (
    PluralsightFlowSource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestPluralsightFlowSource:
    def setup_method(self):
        self.source = PluralsightFlowSource()
        self.team_id = 123
        self.config = PluralsightFlowSourceConfig(workspace="acme", api_key="key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.PLURALSIGHTFLOW

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "PluralsightFlow"
        assert config.label == "Pluralsight Flow"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/pluralsight_flow.png"
        assert config.category is not None

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["workspace", "api_key"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    def test_workspace_field_is_not_secret(self):
        config = self.source.get_source_config
        workspace_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "workspace"
        )
        assert workspace_field.secret is False
        assert workspace_field.required is True

    def test_workspace_listed_as_connection_host_field(self):
        # The API key is sent to <workspace>.appfireflow.com, so retargeting the workspace must
        # re-require it.
        assert self.source.connection_host_fields == ["workspace"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://acme.appfireflow.com/v3/customer/core/users/",
            "403 Client Error: Forbidden for url: https://api.appfireflow.com/collaboration/code/metrics/",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://acme.appfireflow.com/v3/customer/core/users/",
            "500 Server Error: Internal Server Error for url: https://acme.appfireflow.com/v3/customer/core/users/",
            "HTTPSConnectionPool(host='acme.appfireflow.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_match_all_endpoints(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        assert set(schemas) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        ("name", "field"),
        [
            ("Users", "last_activity_at"),
            ("Teams", "created_at"),
            ("Commits", "author_date"),
            ("PullRequests", "created_at"),
            ("Tickets", "updated_at"),
        ],
    )
    def test_get_schemas_incremental_endpoints(self, name, field):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[name].supports_incremental is True
        assert [f["field"] for f in schemas[name].incremental_fields] == [field]

    @pytest.mark.parametrize("name", ["Repos", "CodingMetrics", "CollaborationMetrics"])
    def test_get_schemas_full_refresh_endpoints(self, name):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[name].supports_incremental is False
        assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Commits"])
        assert len(schemas) == 1
        assert schemas[0].name == "Commits"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials_publishes_catalog(self):
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Your Flow API key is invalid or expired."),
            ((False, 403), False, "Invalid credentials"),
            ((False, None), False, "Invalid credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pluralsight_flow.source"
        ".validate_pluralsight_flow_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key", "acme")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pluralsight_flow.source"
        ".validate_pluralsight_flow_credentials"
    )
    def test_validate_credentials_surfaces_bad_workspace(self, mock_validate):
        mock_validate.side_effect = ValueError("Invalid Flow workspace: 'a/b'.")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "Invalid Flow workspace" in (error_message or "")

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is PluralsightFlowResumeConfig

    @pytest.mark.parametrize("endpoint", list(CORE_ENDPOINTS) + list(METRIC_ENDPOINTS))
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pluralsight_flow.source.pluralsight_flow_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_pluralsight_flow_source, endpoint):
        inputs = mock.MagicMock()
        inputs.schema_name = endpoint
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_pluralsight_flow_source.assert_called_once()
        kwargs = mock_pluralsight_flow_source.call_args.kwargs
        assert kwargs["workspace"] == "acme"
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == endpoint
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pluralsight_flow.source.pluralsight_flow_source"
    )
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_pluralsight_flow_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Repos"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_pluralsight_flow_source.call_args.kwargs["db_incremental_field_last_value"] is None
