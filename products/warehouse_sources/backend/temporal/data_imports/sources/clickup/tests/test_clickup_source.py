import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.clickup.clickup import ClickUpResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.clickup.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clickup.source import ClickUpSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ClickUpSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestClickUpSource:
    def setup_method(self) -> None:
        self.source = ClickUpSource()
        self.team_id = 123
        self.config = ClickUpSourceConfig(api_key="pk_token", workspace_id="9008123456")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CLICKUP

    def test_workspace_id_is_a_connection_host_field(self) -> None:
        # Changing the workspace the token targets must re-require the token.
        assert self.source.connection_host_fields == ["workspace_id"]

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "ClickUp"
        assert config.label == "ClickUp"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/clickup.svg"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key", "workspace_id"]

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        api_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_field.secret is True
        assert api_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.clickup.com/api/v2/team",
            "403 Client Error: Forbidden for url: https://api.clickup.com/api/v2/team/9/task",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.clickup.com/api/v2/team",
        ],
    )
    def test_non_retryable_errors_ignore_unrelated(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only tasks expose ClickUp's server-side date_updated_gt filter.
        assert incremental == {"tasks"}
        assert all(schema.supports_append is False for schema in schemas)

    def test_tasks_schema_advertises_incremental_field(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["tasks"].incremental_fields == INCREMENTAL_FIELDS["tasks"]
        assert schemas["spaces"].incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["tasks"])
        assert len(schemas) == 1
        assert schemas[0].name == "tasks"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Invalid ClickUp API token"), False, "Invalid ClickUp API token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.clickup.source.validate_clickup_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: tuple[bool, str | None],
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, self.config.workspace_id)

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ClickUpResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.clickup.source.clickup_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_clickup_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "tasks"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1567780450202
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_clickup_source.assert_called_once()
        kwargs = mock_clickup_source.call_args.kwargs
        assert kwargs["api_key"] == "pk_token"
        assert kwargs["workspace_id"] == "9008123456"
        assert kwargs["endpoint"] == "tasks"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1567780450202

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.clickup.source.clickup_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_clickup_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "spaces"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1567780450202

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_clickup_source.call_args.kwargs["db_incremental_field_last_value"] is None
