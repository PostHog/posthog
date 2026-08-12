from unittest.mock import Mock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.apitally.apitally import ApitallyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.apitally.source import ApitallySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.apitally import (
    ApitallySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestApitallySourceConfig:
    def setup_method(self) -> None:
        self.source = ApitallySource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.APITALLY

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


class TestApitallySourceSchemas:
    def setup_method(self) -> None:
        self.source = ApitallySource()

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(config=Mock(), team_id=1)

        names = {schema.name for schema in schemas}
        assert names == {"Apps", "Consumers", "Endpoints", "Traffic", "RequestLogs"}

    @parameterized.expand(["Apps", "Consumers", "Endpoints"])
    def test_dimension_endpoints_are_full_refresh_only(self, endpoint: str) -> None:
        schemas = self.source.get_schemas(config=Mock(), team_id=1, names=[endpoint])

        assert len(schemas) == 1
        assert schemas[0].supports_incremental is False
        assert schemas[0].incremental_fields == []

    @parameterized.expand(
        [
            ("Traffic", "period_end"),
            ("RequestLogs", "timestamp"),
        ]
    )
    def test_time_series_endpoints_support_incremental(self, endpoint: str, expected_field: str) -> None:
        schemas = self.source.get_schemas(config=Mock(), team_id=1, names=[endpoint])

        assert len(schemas) == 1
        assert schemas[0].supports_incremental is True
        assert schemas[0].incremental_fields[0]["field"] == expected_field

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(config=Mock(), team_id=1, names=["Apps"])

        assert [schema.name for schema in schemas] == ["Apps"]


class TestApitallySourceCredentialValidation:
    def setup_method(self) -> None:
        self.source = ApitallySource()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.apitally.source.validate_apitally_credentials"
    )
    def test_validate_credentials_delegates_to_transport(self, mock_validate) -> None:
        mock_validate.return_value = (True, None)
        config = ApitallySourceConfig(api_key="test-key")

        result = self.source.validate_credentials(config, team_id=1)

        assert result == (True, None)
        mock_validate.assert_called_once_with("test-key")


class TestApitallySourceNonRetryableErrors:
    def setup_method(self) -> None:
        self.source = ApitallySource()

    @parameterized.expand(
        [
            "401 Client Error",
            "403 Client Error",
        ]
    )
    def test_non_retryable_errors_includes_pattern(self, pattern: str) -> None:
        assert pattern in self.source.get_non_retryable_errors()


class TestApitallySourcePipelinePlumbing:
    def setup_method(self) -> None:
        self.source = ApitallySource()

    def test_get_resumable_source_manager_returns_bound_manager(self) -> None:
        inputs = Mock()
        inputs.team_id = 1
        inputs.job_id = "job-1"
        inputs.logger = Mock()

        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.apitally.source.apitally_source")
    def test_source_for_pipeline_forwards_arguments(self, mock_apitally_source) -> None:
        mock_apitally_source.return_value = Mock()
        config = ApitallySourceConfig(api_key="test-key")
        inputs = Mock()
        inputs.schema_name = "Traffic"
        inputs.team_id = 42
        inputs.job_id = "job-42"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2025-01-01T00:00:00Z"
        inputs.incremental_field = "period_end"
        manager = Mock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(config, manager, inputs)

        mock_apitally_source.assert_called_once_with(
            api_key="test-key",
            endpoint="Traffic",
            team_id=42,
            job_id="job-42",
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2025-01-01T00:00:00Z",
            incremental_field="period_end",
        )

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.apitally.source.apitally_source")
    def test_source_for_pipeline_omits_last_value_when_not_incremental(self, mock_apitally_source) -> None:
        mock_apitally_source.return_value = Mock()
        config = ApitallySourceConfig(api_key="test-key")
        inputs = Mock()
        inputs.schema_name = "Apps"
        inputs.team_id = 42
        inputs.job_id = "job-42"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "should-be-ignored"
        inputs.incremental_field = None
        manager = Mock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(config, manager, inputs)

        _, kwargs = mock_apitally_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None


def test_apitally_resume_config_defaults_to_no_token() -> None:
    assert ApitallyResumeConfig().next_token is None
