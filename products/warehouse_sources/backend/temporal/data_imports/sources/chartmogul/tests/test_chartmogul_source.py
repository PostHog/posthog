import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.chartmogul import (
    ChartMogulResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.source import ChartMogulSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ChartMogulSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestChartMogulSource:
    def setup_method(self) -> None:
        self.source = ChartMogulSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CHARTMOGUL

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name == SchemaExternalDataSourceType.CHART_MOGUL
        assert config.label == "ChartMogul"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.fields is not None
        field_names = [f.name for f in config.fields]
        assert field_names == ["api_key"]

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(ChartMogulSourceConfig(api_key="k"), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = self.source.get_schemas(ChartMogulSourceConfig(api_key="k"), team_id=1, names=["customers"])
        assert [s.name for s in schemas] == ["customers"]

    @pytest.mark.parametrize(
        "endpoint,expected_incremental",
        [
            ("activities", True),
            ("customers", False),
            ("plans", False),
            ("invoices", False),
            ("data_sources", False),
        ],
    )
    def test_supports_incremental_only_for_activities(self, endpoint: str, expected_incremental: bool) -> None:
        schemas = self.source.get_schemas(ChartMogulSourceConfig(api_key="k"), team_id=1, names=[endpoint])
        assert schemas[0].supports_incremental is expected_incremental

    def test_validate_credentials_success(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.source.validate_chartmogul_credentials",
            return_value=True,
        ):
            valid, error = self.source.validate_credentials(ChartMogulSourceConfig(api_key="k"), team_id=1)
        assert valid is True
        assert error is None

    def test_validate_credentials_failure(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.source.validate_chartmogul_credentials",
            return_value=False,
        ):
            valid, error = self.source.validate_credentials(ChartMogulSourceConfig(api_key="bad"), team_id=1)
        assert valid is False
        assert error == "Invalid ChartMogul API key"

    @pytest.mark.parametrize(
        "pattern",
        [
            "401 Client Error: Unauthorized for url: https://api.chartmogul.com",
            "403 Client Error: Forbidden for url: https://api.chartmogul.com",
        ],
    )
    def test_non_retryable_errors_includes_pattern(self, pattern: str) -> None:
        assert pattern in self.source.get_non_retryable_errors()

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ChartMogulResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "activities"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01"
        manager = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.source.chartmogul_source"
        ) as mock_source:
            self.source.source_for_pipeline(ChartMogulSourceConfig(api_key="k"), manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "k"
        assert kwargs["endpoint"] == "activities"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_drops_incremental_value_when_disabled(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "customers"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01"

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.source.chartmogul_source"
        ) as mock_source:
            self.source.source_for_pipeline(ChartMogulSourceConfig(api_key="k"), MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
