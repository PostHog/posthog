from unittest.mock import Mock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sleekplan import (
    SleekplanSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sleekplan.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sleekplan.sleekplan import SleekplanResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sleekplan.source import SleekplanSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.sleekplan.source"


class TestSleekplanSourceConfig:
    def setup_method(self) -> None:
        self.source = SleekplanSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SLEEKPLAN

    def test_source_config_is_released_and_alpha(self) -> None:
        config = self.source.get_source_config

        # A finished source ships with no `unreleasedSource` flag, which would hide it entirely.
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

    @parameterized.expand([("401 Client Error",), ("403 Client Error",)])
    def test_auth_failures_are_non_retryable(self, error: str) -> None:
        assert error in self.source.get_non_retryable_errors()


class TestSleekplanSourceSchemas:
    def setup_method(self) -> None:
        self.source = SleekplanSource()

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(config=Mock(), team_id=1)

        assert {schema.name for schema in schemas} == {
            "Users",
            "Posts",
            "Comments",
            "Votes",
            "Updates",
            "Satisfaction",
            "Promoter",
        }

    @parameterized.expand(["Users", "Posts", "Comments", "Votes", "Updates"])
    def test_endpoints_without_a_server_side_filter_are_full_refresh_only(self, name: str) -> None:
        # Sleekplan only documents `date_start`/`date_end` on the survey endpoints; advertising
        # incremental anywhere else would page the whole collection and call it a delta.
        schemas = self.source.get_schemas(config=Mock(), team_id=1, names=[name])

        assert [schema.supports_incremental for schema in schemas] == [False]
        assert [schema.supports_append for schema in schemas] == [False]
        assert schemas[0].incremental_fields == []

    @parameterized.expand(["Satisfaction", "Promoter"])
    def test_survey_endpoints_are_incremental_merge_only(self, name: str) -> None:
        schemas = self.source.get_schemas(config=Mock(), team_id=1, names=[name])

        assert schemas[0].supports_incremental is True
        # Each run re-reads a trailing window, so appending would duplicate rows.
        assert schemas[0].supports_append is False
        assert [field["field"] for field in schemas[0].incremental_fields] == ["updated"]

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(config=Mock(), team_id=1, names=["Posts"])

        assert [schema.name for schema in schemas] == ["Posts"]

    def test_every_table_has_canonical_descriptions(self) -> None:
        schemas = self.source.get_schemas(config=Mock(), team_id=1)

        assert {schema.name for schema in schemas} == set(self.source.get_canonical_descriptions())
        assert self.source.get_canonical_descriptions() is CANONICAL_DESCRIPTIONS


class TestSleekplanSourceCredentialValidation:
    def setup_method(self) -> None:
        self.source = SleekplanSource()

    @parameterized.expand([("at_source_create", None), ("for_a_schema", "Posts")])
    def test_validate_credentials_delegates_to_transport(self, _name: str, schema_name: str | None) -> None:
        config = SleekplanSourceConfig(api_key="test-key")

        with patch(f"{SOURCE_MODULE}.validate_sleekplan_credentials", return_value=(True, None)) as mock_validate:
            result = self.source.validate_credentials(config, team_id=1, schema_name=schema_name)

        assert result == (True, None)
        mock_validate.assert_called_once_with("test-key", schema_name=schema_name)


class TestSleekplanSourcePipelinePlumbing:
    def setup_method(self) -> None:
        self.source = SleekplanSource()

    def test_get_resumable_source_manager_returns_bound_manager(self) -> None:
        inputs = Mock()
        inputs.team_id = 1
        inputs.job_id = "job-1"
        inputs.logger = Mock()

        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SleekplanResumeConfig

    def test_source_for_pipeline_forwards_arguments(self) -> None:
        config = SleekplanSourceConfig(api_key="test-key")
        inputs = Mock()
        inputs.schema_name = "Promoter"
        inputs.team_id = 42
        inputs.job_id = "job-42"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2025-01-01T00:00:00Z"
        inputs.incremental_field = "updated"
        manager = Mock(spec=ResumableSourceManager)

        with patch(f"{SOURCE_MODULE}.sleekplan_source", return_value=Mock()) as mock_source:
            self.source.source_for_pipeline(config, manager, inputs)

        mock_source.assert_called_once_with(
            api_key="test-key",
            endpoint="Promoter",
            team_id=42,
            job_id="job-42",
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2025-01-01T00:00:00Z",
            incremental_field="updated",
        )

    def test_source_for_pipeline_omits_last_value_when_not_incremental(self) -> None:
        config = SleekplanSourceConfig(api_key="test-key")
        inputs = Mock()
        inputs.schema_name = "Posts"
        inputs.team_id = 42
        inputs.job_id = "job-42"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "should-be-ignored"
        inputs.incremental_field = None
        manager = Mock(spec=ResumableSourceManager)

        with patch(f"{SOURCE_MODULE}.sleekplan_source", return_value=Mock()) as mock_source:
            self.source.source_for_pipeline(config, manager, inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
