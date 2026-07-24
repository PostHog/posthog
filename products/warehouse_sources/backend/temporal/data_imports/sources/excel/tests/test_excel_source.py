from collections.abc import AsyncIterable

from unittest.mock import patch

from django.test import SimpleTestCase

import structlog

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.excel.excel import ExcelReadError
from products.warehouse_sources.backend.temporal.data_imports.sources.excel.source import ExcelSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.excel import ExcelSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.excel.source"


def _config() -> ExcelSourceConfig:
    return ExcelSourceConfig(upload_id="u1", filename="book.xlsx")


class TestExcelSource(SimpleTestCase):
    def setUp(self) -> None:
        self.source = ExcelSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.EXCEL

    def test_config_is_visible_and_categorized(self) -> None:
        # unreleasedSource hides a source from users entirely — a finished source must not set it.
        config = self.source.get_source_config

        assert config.label == "Excel"
        assert config.category is not None and config.category.value == "File storage"
        assert getattr(config, "unreleasedSource", None) in (None, False)
        assert [field.name for field in config.fields] == ["upload_id", "filename"]

    def test_column_selection_is_advertised(self) -> None:
        # The reader projects rows by enabled_columns, so the flag has to match that capability.
        assert self.source.supports_column_selection is True

    def test_does_not_list_tables_without_credentials(self) -> None:
        # Discovery opens the workbook from S3, so it must never run against a placeholder config
        # for the public docs catalog.
        assert self.source.lists_tables_without_credentials is False

    def test_get_schemas_returns_one_full_refresh_schema_per_sheet(self) -> None:
        with patch(
            f"{SOURCE_MODULE}.list_sheets",
            return_value=[("Orders", ["id", "total"]), ("Refunds", ["id"])],
        ):
            schemas = self.source.get_schemas(_config(), team_id=1)

        assert [schema.name for schema in schemas] == ["Orders", "Refunds"]
        # A static file has no cursor, so neither incremental nor append may be offered.
        assert all(not schema.supports_incremental and not schema.supports_append for schema in schemas)
        assert schemas[0].columns == [("id", "string", True), ("total", "string", True)]

    def test_get_schemas_honors_the_names_filter(self) -> None:
        with patch(
            f"{SOURCE_MODULE}.list_sheets",
            return_value=[("Orders", ["id"]), ("Refunds", ["id"])],
        ):
            schemas = self.source.get_schemas(_config(), team_id=1, names=["Refunds"])

        assert [schema.name for schema in schemas] == ["Refunds"]

    def test_validate_credentials_rejects_a_missing_upload(self) -> None:
        # The reference, not a credential, is what can be wrong here — catch it at setup rather
        # than letting the first sync fail.
        with patch(f"{SOURCE_MODULE}.uploaded_file_exists", return_value=False):
            valid, error = self.source.validate_credentials(_config(), team_id=1)

        assert valid is False
        assert error is not None and "upload" in error.lower()

    def test_validate_credentials_surfaces_an_unreadable_workbook(self) -> None:
        with (
            patch(f"{SOURCE_MODULE}.uploaded_file_exists", return_value=True),
            patch(f"{SOURCE_MODULE}.list_sheets", side_effect=ExcelReadError("Could not read the Excel file.")),
        ):
            valid, error = self.source.validate_credentials(_config(), team_id=1)

        assert valid is False
        assert error == "Could not read the Excel file."

    def test_validate_credentials_rejects_a_workbook_with_no_usable_sheets(self) -> None:
        with (
            patch(f"{SOURCE_MODULE}.uploaded_file_exists", return_value=True),
            patch(f"{SOURCE_MODULE}.list_sheets", return_value=[]),
        ):
            valid, error = self.source.validate_credentials(_config(), team_id=1)

        assert valid is False
        assert error is not None and "no sheets" in error.lower()

    def test_validate_credentials_accepts_a_readable_workbook(self) -> None:
        with (
            patch(f"{SOURCE_MODULE}.uploaded_file_exists", return_value=True),
            patch(f"{SOURCE_MODULE}.list_sheets", return_value=[("Orders", ["id"])]),
        ):
            assert self.source.validate_credentials(_config(), team_id=1) == (True, None)

    def test_source_for_pipeline_reads_the_requested_sheet_with_column_selection(self) -> None:
        inputs = _source_inputs(schema_name="Orders", enabled_columns=["id"])

        with patch(f"{SOURCE_MODULE}.read_sheet_rows", return_value=iter([[{"id": 1}]])) as read_rows:
            response = self.source.source_for_pipeline(_config(), inputs)
            rows = response.items()
            assert not isinstance(rows, AsyncIterable)
            list(rows)

        assert response.name == "Orders"
        # No stable row identity in a spreadsheet, so the table is replaced rather than merged.
        assert response.primary_keys is None
        read_rows.assert_called_once_with(7, "u1", "book.xlsx", "Orders", enabled_columns=["id"])


def _source_inputs(*, schema_name: str, enabled_columns: list[str] | None = None) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="s1",
        source_id="src1",
        team_id=7,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="j1",
        logger=structlog.get_logger(__name__),
        reset_pipeline=False,
        enabled_columns=enabled_columns,
    )


class TestExcelSyncCadence(SimpleTestCase):
    def test_excel_syncs_once(self) -> None:
        # The workbook never changes upstream, so the schedule is created paused and the initial
        # import is the explicit trigger. The create flow reads this flag to decide.
        assert ExcelSource().syncs_once is True

    def test_syncs_once_defaults_off_for_other_sources(self) -> None:
        # Every feed-backed source must keep its recurring schedule — this flag is opt-in only.
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import _BaseSource

        assert _BaseSource.syncs_once is False
