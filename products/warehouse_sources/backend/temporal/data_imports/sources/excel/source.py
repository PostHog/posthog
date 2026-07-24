from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.excel.excel import (
    ExcelReadError,
    list_sheets,
    read_sheet_rows,
    uploaded_file_exists,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.excel import ExcelSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ExcelSource(SimpleSource[ExcelSourceConfig]):
    """An uploaded Excel workbook, synced as one table per sheet.

    Unlike every other source there is no vendor API: the workbook sits in PostHog's own bucket,
    put there by the file-upload endpoint, and the source holds a reference to it. Going through the
    source pipeline rather than converting the file in the upload request is what keeps the work
    (openpyxl is CPU-bound) on the data-warehouse workers, and is what gives the workbook per-sheet
    tables, column selection, and job history for free.

    The file is static, so syncs are full refreshes and the schedule is created paused — the initial
    import is triggered explicitly and re-syncing is a deliberate act (which doubles as the way to
    pick up a replaced file).
    """

    # Sheets are discovered by opening the workbook, so discovery does I/O and can't run against a
    # placeholder config for the public docs table catalog.
    lists_tables_without_credentials = False

    # The workbook is a snapshot, not a feed: import it once and let a refresh be a manual sync
    # (which is also how a replaced file gets picked up).
    syncs_once = True

    # Column selection is honored by projecting the row down while reading the sheet.
    supports_column_selection = True

    # No vendor API, so no version to pin — left at the unversioned default. The docs link points at
    # the workbook format the reader supports.
    api_docs_url = "https://learn.microsoft.com/en-us/openspecs/office_standards/ms-xlsx/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EXCEL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.EXCEL,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            label="Excel",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Upload an Excel workbook to query it in the PostHog Data warehouse. Each sheet becomes its own table, and you choose which sheets and columns to sync.

Supports `.xlsx` and `.xlsm`. Re-run the sync after replacing the file to pick up new data.""",
            # Reuses the committed file-upload icon: apt for an uploaded workbook, and adding a
            # real Excel logo needs a Logo.dev key we don't hold here.
            iconPath="/static/services/file-upload.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/excel",
            keywords=["excel", "xlsx", "xlsm", "spreadsheet", "workbook", "upload"],
            fields=cast(
                list[FieldType],
                [
                    # Both fields identify the already-uploaded workbook in our bucket. The upload
                    # step fills them in — a binary file can't ride the generic source form, since
                    # `SourceFieldFileUploadConfig` only accepts JSON.
                    SourceFieldInputConfig(
                        name="upload_id",
                        label="Upload ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="filename",
                        label="File name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: ExcelSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        sheets = list_sheets(team_id, config.upload_id, config.filename)
        return [
            SourceSchema(
                name=sheet_name,
                supports_incremental=False,
                supports_append=False,
                # A static file has no cursor to advance, so full refresh is the only sync method.
                incremental_fields=[],
                # Reported so the column picker has names to show. Types are left as strings here;
                # the real schema is inferred from the cell values when the sheet syncs.
                columns=[(column, "string", True) for column in columns],
            )
            for sheet_name, columns in sheets
            if names is None or sheet_name in names
        ]

    def validate_credentials(
        self,
        config: ExcelSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        """There are no credentials — the workbook is ours. What can fail is the reference: an
        upload_id/filename that no longer resolves, or a file openpyxl can't read. Checking both here
        means a bad reference fails at setup rather than on the first sync."""
        if not uploaded_file_exists(team_id, config.upload_id, config.filename):
            return False, "Uploaded file not found. Please upload the workbook again."
        try:
            sheets = list_sheets(team_id, config.upload_id, config.filename)
        except ExcelReadError as error:
            return False, str(error)
        if not sheets:
            return False, "No sheets with a header row were found in this workbook."
        return True, None

    def source_for_pipeline(self, config: ExcelSourceConfig, inputs: SourceInputs) -> SourceResponse:
        def get_rows():
            return read_sheet_rows(
                inputs.team_id,
                config.upload_id,
                config.filename,
                inputs.schema_name,
                enabled_columns=inputs.enabled_columns,
            )

        return SourceResponse(
            name=inputs.schema_name,
            items=get_rows,
            # A spreadsheet row has no reliable identity, so there's no key to merge on — each sync
            # fully replaces the table, which is the right semantics for re-importing a file.
            primary_keys=None,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Uploaded file not found": "The uploaded file is no longer in storage. Upload the workbook again.",
            "Could not read the Excel file": "The file isn't a readable .xlsx or .xlsm workbook. Re-save it and upload again.",
        }
