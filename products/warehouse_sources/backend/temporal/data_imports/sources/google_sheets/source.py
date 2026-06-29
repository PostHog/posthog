from typing import Optional, cast

from django.conf import settings

import gspread

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GoogleSheetsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.google_sheets.google_sheets import (
    get_schema_incremental_fields as get_google_sheets_schema_incremental_fields,
    get_schemas as get_google_sheets_schemas,
    google_sheets_client,
    google_sheets_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GoogleSheetsSource(SimpleSource[GoogleSheetsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLESHEETS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "the header row in the worksheet contains duplicates": "Import failed: There exists duplicate column headers. Please make sure all column headers have values and aren't duplicated.",
            "can't be found": None,
            "must be real number, not str": "Import failed: a numeric column contains a non-numeric value. Ensure every cell in numeric columns is stored as a plain number.",
            "Spreadsheet access denied": "Import failed: PostHog does not have access to this spreadsheet. Please share it with our service account as described at https://posthog.com/docs/cdp/sources/google-sheets",
            # gspread surfaces the Sheets API 404 (deleted/moved sheet, or access removed) as a
            # `SpreadsheetNotFound`, which `google_sheets.py` re-raises with this stable message —
            # `str(SpreadsheetNotFound)` is otherwise just `<Response [404]>`, with nothing to match.
            # Retrying cannot recover.
            "Spreadsheet not found": "Import failed: the Google Sheet could not be found. It may have been deleted or moved. Please check the spreadsheet URL and that it is shared with our service account.",
        }

    def get_schemas(
        self,
        config: GoogleSheetsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        sheets = get_google_sheets_schemas(config)

        if names is not None:
            names_set = set(names)
            sheets = [(name, row_count) for name, row_count in sheets if name in names_set]

        schemas: list[SourceSchema] = []
        for name, _ in sheets:
            incremental_fields = get_google_sheets_schema_incremental_fields(config, name)

            schemas.append(
                SourceSchema(
                    name=name,
                    supports_incremental=len(incremental_fields) > 0,
                    supports_append=len(incremental_fields) > 0,
                    incremental_fields=incremental_fields,
                )
            )

        return schemas

    def source_for_pipeline(self, config: GoogleSheetsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return google_sheets_source(
            config,
            inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    def validate_credentials(
        self, config: GoogleSheetsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        client = google_sheets_client()
        try:
            client.open_by_url(config.spreadsheet_url)
            return True, None
        except gspread.SpreadsheetNotFound:
            return False, "Spreadsheet not found at URL provided"
        except PermissionError:
            return (
                False,
                "Permissions missing from spreadsheet. View documentation at https://posthog.com/docs/cdp/sources/google-sheets",
            )
        except Exception as e:
            return False, str(e)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_SHEETS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Google Sheets",
            caption="Ensure you have granted PostHog access to your Google Sheet as instructed in the [documentation](https://posthog.com/docs/cdp/sources/google-sheets)",
            releaseStatus=ReleaseStatus.GA,
            iconPath="/static/services/Google_Sheets.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/google-sheets",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="spreadsheet_url",
                        label="Spreadsheet URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        caption=f'Share the sheet with our service account by entering **{settings.GOOGLE_SHEETS_SERVICE_ACCOUNT_CLIENT_EMAIL}** into the "Add people" field. We only require "Viewer" permissions to sync the sheet.',
                        secret=False,
                    )
                ],
            ),
            featured=True,
        )
