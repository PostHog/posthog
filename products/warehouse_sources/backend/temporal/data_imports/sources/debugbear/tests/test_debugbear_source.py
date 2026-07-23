import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.debugbear.source import DebugbearSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.debugbear import (
    DebugbearSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestDebugbearSource:
    def setup_method(self) -> None:
        self.source = DebugbearSource()
        self.team_id = 123
        self.config = DebugbearSourceConfig(api_key="test-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.DEBUGBEAR

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs table
        # catalog can render without a real credential.
        assert self.source.lists_tables_without_credentials is True

    def test_get_source_config_has_no_unreleased_flag(self) -> None:
        # A finished source must not stay hidden behind unreleasedSource.
        assert self.source.get_source_config.unreleasedSource is None

    def test_get_source_config_release_status(self) -> None:
        assert self.source.get_source_config.releaseStatus == ReleaseStatus.ALPHA

    def test_get_source_config_has_category(self) -> None:
        assert self.source.get_source_config.category is not None

    def test_get_source_config_api_key_field(self) -> None:
        fields = self.source.get_source_config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_key"
        assert field.secret is True
        assert field.required is True

    def test_get_schemas_returns_expected_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == {"Projects", "PageMetrics"}

    def test_get_schemas_projects_is_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        projects = next(s for s in schemas if s.name == "Projects")
        assert projects.supports_incremental is False
        assert projects.incremental_fields == []

    def test_get_schemas_page_metrics_supports_incremental(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        page_metrics = next(s for s in schemas if s.name == "PageMetrics")
        assert page_metrics.supports_incremental is True
        assert [f["field"] for f in page_metrics.incremental_fields] == ["analysis_date"]

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Projects"])
        assert [s.name for s in schemas] == ["Projects"]

    @pytest.mark.parametrize(
        ("pattern", "message"),
        [
            ("401 Client Error", "401 Client Error: Unauthorized for url: https://www.debugbear.com/api/v1/projects"),
            ("403 Client Error", "403 Client Error: Forbidden for url: https://www.debugbear.com/api/v1/projects"),
        ],
    )
    def test_non_retryable_errors_match(self, pattern: str, message: str) -> None:
        errors = self.source.get_non_retryable_errors()
        assert pattern in errors
        assert any(p in message for p in errors)

    def test_validate_credentials_delegates_to_transport(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.debugbear.source.validate_debugbear_credentials"
        ) as mock_validate:
            mock_validate.return_value = (True, None)
            result = self.source.validate_credentials(self.config, self.team_id)

        mock_validate.assert_called_once_with("test-key")
        assert result == (True, None)

    def test_get_canonical_descriptions_covers_declared_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == {"Projects", "PageMetrics"}

    @pytest.mark.parametrize("schema_name", ["Projects", "PageMetrics"])
    def test_source_for_pipeline_plumbs_schema_name(self, schema_name: str) -> None:
        inputs = MagicMock(spec=SourceInputs)
        inputs.schema_name = schema_name
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = None

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.debugbear.source.debugbear_source"
        ) as mock_debugbear_source:
            self.source.source_for_pipeline(self.config, inputs)

        mock_debugbear_source.assert_called_once_with(
            api_key="test-key",
            endpoint=schema_name,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )

    def test_source_for_pipeline_omits_watermark_when_not_incremental(self) -> None:
        inputs = MagicMock(spec=SourceInputs)
        inputs.schema_name = "PageMetrics"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.debugbear.source.debugbear_source"
        ) as mock_debugbear_source:
            self.source.source_for_pipeline(self.config, inputs)

        assert mock_debugbear_source.call_args.kwargs["db_incremental_field_last_value"] is None
