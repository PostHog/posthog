from typing import Any

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.profound.profound import ProfoundResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.profound.source import ProfoundSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.profound.source"


class _Config:
    api_key = "key"


def _inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "Visibility",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestProfoundSource:
    def test_source_type(self) -> None:
        assert ProfoundSource().source_type == ExternalDataSourceType.PROFOUND

    def test_schemas_cover_the_endpoint_catalog(self) -> None:
        schemas = ProfoundSource().get_schemas(None, 1)  # type: ignore[arg-type]

        assert [s.name for s in schemas] == [
            "Categories",
            "Models",
            "Regions",
            "Domains",
            "Assets",
            "Personas",
            "Visibility",
            "Citations",
        ]

    @parameterized.expand(
        [
            ("visibility_is_incremental", "Visibility", True),
            ("citations_is_incremental", "Citations", True),
            ("categories_is_not", "Categories", False),
            ("assets_is_not", "Assets", False),
            ("personas_is_not", "Personas", False),
        ]
    )
    def test_only_the_report_tables_are_incremental(self, _name: str, endpoint: str, expected: bool) -> None:
        # The reference lists carry no time filter, so advertising incremental would promise a cheap
        # sync that still reads everything.
        schemas = {s.name: s for s in ProfoundSource().get_schemas(None, 1)}  # type: ignore[arg-type]

        assert schemas[endpoint].supports_incremental is expected

    @parameterized.expand([("Visibility",), ("Citations",)])
    def test_reports_track_the_date_column(self, endpoint: str) -> None:
        # `date` only appears on a row because the request groups by it.
        schemas = {s.name: s for s in ProfoundSource().get_schemas(None, 1)}  # type: ignore[arg-type]

        assert [f["field"] for f in schemas[endpoint].incremental_fields] == ["date"]

    @parameterized.expand([("valid", True, True), ("rejected", False, False)])
    @mock.patch(f"{SOURCE_MODULE}.validate_profound_credentials")
    def test_validate_credentials(self, _name: str, probe_ok: bool, expected: bool, mock_validate) -> None:
        mock_validate.return_value = probe_ok

        ok, message = ProfoundSource().validate_credentials(_Config(), 1)  # type: ignore[arg-type]

        assert ok is expected
        assert (message is None) is expected

    def test_resumable_manager_is_bound_to_the_resume_dataclass(self) -> None:
        manager = ProfoundSource().get_resumable_source_manager(_inputs())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ProfoundResumeConfig

    @mock.patch(f"{SOURCE_MODULE}.profound_source")
    def test_source_for_pipeline_passes_the_watermark_when_incremental(self, mock_source) -> None:
        inputs = _inputs(should_use_incremental_field=True, db_incremental_field_last_value="2026-06-01")

        ProfoundSource().source_for_pipeline(_Config(), mock.MagicMock(), inputs)  # type: ignore[arg-type]

        kwargs = mock_source.call_args.kwargs
        assert kwargs["endpoint"] == "Visibility"
        assert kwargs["db_incremental_field_last_value"] == "2026-06-01"

    @mock.patch(f"{SOURCE_MODULE}.profound_source")
    def test_source_for_pipeline_drops_the_watermark_on_full_refresh(self, mock_source) -> None:
        # A stale watermark would shorten the report window a user asked to re-import in full.
        inputs = _inputs(should_use_incremental_field=False, db_incremental_field_last_value="2026-06-01")

        ProfoundSource().source_for_pipeline(_Config(), mock.MagicMock(), inputs)  # type: ignore[arg-type]

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_is_visible_and_labelled_alpha(self) -> None:
        # unreleasedSource=True hides the connector from users entirely; this source is finished.
        config = ProfoundSource().get_source_config

        assert config.unreleasedSource is None
        assert config.releaseStatus == "alpha"
        assert config.category is not None
        assert config.iconPath == "/static/services/profound.png"
