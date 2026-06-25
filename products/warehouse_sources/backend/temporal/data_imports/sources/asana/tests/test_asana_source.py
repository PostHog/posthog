import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.asana.asana import AsanaResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.asana.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.asana.source import AsanaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AsanaSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestAsanaSource:
    def setup_method(self):
        self.source = AsanaSource()
        self.team_id = 123
        self.config = AsanaSourceConfig(access_token="1/abc")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.ASANA

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Asana"
        assert config.label == "Asana"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/asana.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["access_token"]

    def test_access_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "access_token"
        )
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://app.asana.com/api/1.0/workspaces?limit=100",
            "403 Client Error: Forbidden for url: https://app.asana.com/api/1.0/tasks?project=1",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://app.asana.com/api/1.0/users",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas_covers_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_get_schemas_full_refresh_only(self):
        # No endpoint advertises incremental until the tasks `modified_since` filter is verified.
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
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Asana personal access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.asana.source.validate_asana_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.access_token)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AsanaResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.asana.source.asana_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_asana_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "tasks"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_asana_source.assert_called_once()
        kwargs = mock_asana_source.call_args.kwargs
        assert kwargs["access_token"] == "1/abc"
        assert kwargs["endpoint"] == "tasks"
        assert kwargs["resumable_source_manager"] is manager
