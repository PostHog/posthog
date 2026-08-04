from unittest.mock import Mock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.bugherd import BugherdResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.source import BugherdSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bugherd import (
    BugherdSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestBugherdSourceConfig:
    def setup_method(self) -> None:
        self.source = BugherdSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.BUGHERD

    def test_source_config_is_released_and_alpha(self) -> None:
        config = self.source.get_source_config

        # A finished source must ship with no `unreleasedSource` flag — see
        # implementing-warehouse-sources skill.
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_source_config_has_single_api_key_field(self) -> None:
        config = self.source.get_source_config

        assert len(config.fields) == 1
        field = config.fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_key"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True
        assert field.secret is True

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas iterates a static endpoint catalog with no I/O.
        assert self.source.lists_tables_without_credentials is True


class TestBugherdSourceSchemas:
    def setup_method(self) -> None:
        self.source = BugherdSource()

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(config=Mock(), team_id=1)

        names = {schema.name for schema in schemas}
        assert names == {"Organization", "Users", "Projects", "Tasks"}

    @parameterized.expand(["Organization", "Users", "Projects"])
    def test_dimension_endpoints_are_full_refresh_only(self, endpoint: str) -> None:
        schemas = self.source.get_schemas(config=Mock(), team_id=1, names=[endpoint])

        assert len(schemas) == 1
        assert schemas[0].supports_incremental is False
        assert schemas[0].incremental_fields == []

    def test_tasks_supports_incremental_with_two_field_choices(self) -> None:
        schemas = self.source.get_schemas(config=Mock(), team_id=1, names=["Tasks"])

        assert len(schemas) == 1
        assert schemas[0].supports_incremental is True
        fields = {f["field"] for f in schemas[0].incremental_fields}
        assert fields == {"updated_at", "created_at"}

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(config=Mock(), team_id=1, names=["Projects"])

        assert [schema.name for schema in schemas] == ["Projects"]


class TestBugherdSourceCredentialValidation:
    def setup_method(self) -> None:
        self.source = BugherdSource()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.source.validate_bugherd_credentials"
    )
    def test_validate_credentials_delegates_to_transport(self, mock_validate) -> None:
        mock_validate.return_value = (True, None)
        config = BugherdSourceConfig(api_key="test-key")

        result = self.source.validate_credentials(config, team_id=1)

        assert result == (True, None)
        mock_validate.assert_called_once_with("test-key", schema_name=None)

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.source.validate_bugherd_credentials"
    )
    def test_validate_credentials_forwards_schema_name(self, mock_validate) -> None:
        mock_validate.return_value = (False, "missing scope")
        config = BugherdSourceConfig(api_key="test-key")

        result = self.source.validate_credentials(config, team_id=1, schema_name="Tasks")

        assert result == (False, "missing scope")
        mock_validate.assert_called_once_with("test-key", schema_name="Tasks")


class TestBugherdSourceNonRetryableErrors:
    def setup_method(self) -> None:
        self.source = BugherdSource()

    def test_non_retryable_errors_includes_unauthorized(self) -> None:
        assert "401 Client Error" in self.source.get_non_retryable_errors()


class TestBugherdSourcePipelinePlumbing:
    def setup_method(self) -> None:
        self.source = BugherdSource()

    def test_get_resumable_source_manager_returns_bound_manager(self) -> None:
        inputs = Mock()
        inputs.team_id = 1
        inputs.job_id = "job-1"
        inputs.logger = Mock()

        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is BugherdResumeConfig

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.source.bugherd_source")
    def test_source_for_pipeline_forwards_arguments(self, mock_bugherd_source) -> None:
        mock_bugherd_source.return_value = Mock()
        config = BugherdSourceConfig(api_key="test-key")
        inputs = Mock()
        inputs.schema_name = "Tasks"
        inputs.team_id = 42
        inputs.job_id = "job-42"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2025-01-01T00:00:00Z"
        inputs.incremental_field = "updated_at"
        manager = Mock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(config, manager, inputs)

        mock_bugherd_source.assert_called_once_with(
            api_key="test-key",
            endpoint="Tasks",
            team_id=42,
            job_id="job-42",
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2025-01-01T00:00:00Z",
            incremental_field="updated_at",
        )

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.source.bugherd_source")
    def test_source_for_pipeline_omits_last_value_when_not_incremental(self, mock_bugherd_source) -> None:
        mock_bugherd_source.return_value = Mock()
        config = BugherdSourceConfig(api_key="test-key")
        inputs = Mock()
        inputs.schema_name = "Projects"
        inputs.team_id = 42
        inputs.job_id = "job-42"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "should-be-ignored"
        inputs.incremental_field = None
        manager = Mock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(config, manager, inputs)

        _, kwargs = mock_bugherd_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None


def test_bugherd_resume_config_requires_page() -> None:
    resume_config = BugherdResumeConfig(page=7)
    assert resume_config.page == 7
