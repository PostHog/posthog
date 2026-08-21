from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.selectstar import (
    SelectStarSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.select_star.select_star import (
    SelectStarResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.select_star.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.select_star.source import SelectStarSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSelectStarSource:
    def setup_method(self):
        self.source = SelectStarSource()
        self.team_id = 42

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.SELECTSTAR

    def test_source_is_released(self):
        # A finished source must be visible: no unreleasedSource flag, soft ALPHA label.
        config = self.source.get_source_config
        assert getattr(config, "unreleasedSource", None) in (None, False)
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_source_config_basics(self):
        config = self.source.get_source_config
        assert config.label == "Select Star"
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/select-star"
        assert config.iconPath == "/static/services/select_star.png"

    def test_source_config_fields(self):
        fields = {f.name: f for f in self.source.get_source_config.fields}
        assert set(fields) == {"api_token"}

        token = fields["api_token"]
        assert isinstance(token, SourceFieldInputConfig)
        assert token.type == SourceFieldInputConfigType.PASSWORD
        assert token.required is True
        assert token.secret is True

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog with no I/O, so public docs may render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(mock.MagicMock(), self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_tables_and_tags_are_incremental(self):
        schemas = {s.name: s for s in self.source.get_schemas(mock.MagicMock(), self.team_id)}
        assert schemas["Tables"].supports_incremental is True
        assert [f["field"] for f in schemas["Tables"].incremental_fields] == ["updated_on", "last_queried_on"]
        assert schemas["Tags"].supports_incremental is True
        assert [f["field"] for f in schemas["Tags"].incremental_fields] == ["updated_on"]
        for name in ("Columns", "Databases", "Schemas", "Dashboards"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filters_by_name(self):
        schemas = self.source.get_schemas(mock.MagicMock(), self.team_id, names=["Tables"])
        assert [s.name for s in schemas] == ["Tables"]

    def test_validate_credentials_delegates(self):
        config = SelectStarSourceConfig(api_token="tok")
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.select_star.source.validate_selectstar_credentials",
            return_value=(True, None),
        ) as mock_validate:
            assert self.source.validate_credentials(config, self.team_id) == (True, None)
            mock_validate.assert_called_once_with("tok")

    def test_non_retryable_errors_cover_auth(self):
        errors = self.source.get_non_retryable_errors()
        assert "401 Client Error: Unauthorized" in errors
        assert "403 Client Error: Forbidden" in errors

    def test_canonical_descriptions_present(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(ENDPOINTS).issubset(set(canonical))
        assert "guid" in canonical["Tables"]["columns"]

    def test_resumable_manager_bound_to_data_class(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SelectStarResumeConfig

    def test_source_for_pipeline_plumbs_config(self):
        config = SelectStarSourceConfig(api_token="tok")
        inputs = mock.MagicMock()
        inputs.schema_name = "Tables"
        inputs.team_id = 7
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "updated_on"
        manager = mock.MagicMock()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.select_star.source.select_star_source"
        ) as mock_select_star_source:
            self.source.source_for_pipeline(config, manager, inputs)

        mock_select_star_source.assert_called_once_with(
            api_token="tok",
            endpoint="Tables",
            team_id=7,
            job_id="job-1",
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="updated_on",
        )

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self):
        config = SelectStarSourceConfig(api_token="tok")
        inputs = mock.MagicMock()
        inputs.schema_name = "Columns"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "should-be-ignored"
        inputs.incremental_field = None
        manager = mock.MagicMock()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.select_star.source.select_star_source"
        ) as mock_select_star_source:
            self.source.source_for_pipeline(config, manager, inputs)

        assert mock_select_star_source.call_args.kwargs["db_incremental_field_last_value"] is None
