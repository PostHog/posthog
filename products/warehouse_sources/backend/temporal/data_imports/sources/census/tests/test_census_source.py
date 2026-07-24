import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.census.census import CensusResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.census.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.census.source import CensusSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.census import CensusSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCensusSource:
    def setup_method(self) -> None:
        self.source = CensusSource()
        self.team_id = 123
        self.config = CensusSourceConfig(api_key="census-key", region="us")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CENSUS

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Census"
        assert config.label == "Census (Fivetran)"
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # The source ships visible: unreleasedSource hides the connector from every user.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/census.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/census"

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_region_field_defaults_to_us(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldSelectConfig) and f.name == "region")
        assert field.defaultValue == "us"
        assert {option.value for option in field.options} == {"us", "eu"}

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_all_full_refresh(self) -> None:
        # Census has no server-side timestamp filter on any list endpoint, so nothing supports
        # incremental sync.
        schemas = self.source.get_schemas(self.config, self.team_id)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["sync_runs"])
        assert len(schemas) == 1
        assert schemas[0].name == "sync_runs"

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://app.getcensus.com/api/v1/syncs",
            "403 Client Error: Forbidden for url: https://app.getcensus.com/api/v1/syncs",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_non_retryable_errors_ignore_transient_failures(self) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(
            key in "500 Server Error for url: https://app.getcensus.com/api/v1/syncs" for key in non_retryable
        )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.census.source.validate_census_credentials"
    )
    def test_validate_credentials_plumbs_arguments(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        result = self.source.validate_credentials(self.config, self.team_id, schema_name="sync_runs")

        assert result == (True, None)
        mock_validate.assert_called_once_with("census-key", "us", schema_name="sync_runs")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CensusResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.census.source.census_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_census_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "sync_runs"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_census_source.call_args.kwargs
        assert kwargs["api_key"] == "census-key"
        assert kwargs["region"] == "us"
        assert kwargs["endpoint"] == "sync_runs"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
