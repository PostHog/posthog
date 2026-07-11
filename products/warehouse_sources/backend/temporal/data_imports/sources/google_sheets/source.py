from typing import Optional, cast

from django.conf import settings

import gspread
from google.auth import exceptions as google_auth_exceptions

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
            # The values-read calls (`get_all_values`/`get_all_records`) hit the Sheets API directly and
            # gspread does NOT wrap their 404 into `SpreadsheetNotFound` — it raises the raw `APIError`,
            # whose `str()` is "APIError: [404]: Requested entity was not found." (Google's stable 404
            # text). So the sheet/worksheet vanishing mid-read bypasses the `SpreadsheetNotFound` branch
            # above and would be retried forever. The 404 is deterministic — retrying cannot recover.
            "Requested entity was not found": "Import failed: the Google Sheet or worksheet could not be found. It may have been deleted or moved, or is no longer shared with our service account. Please check the spreadsheet URL and its sharing settings.",
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
        except gspread.exceptions.APIError as e:
            # gspread stringifies these as "APIError: [<code>]: <message>", which isn't actionable.
            # The common case is an uploaded Office file (.xlsx) the Sheets API can't read.
            api_message = str(e.error.get("message", "")) if isinstance(e.error, dict) else ""
            if "Office file" in api_message:
                return (
                    False,
                    "This spreadsheet is an uploaded Office file (e.g. .xlsx), which the Google Sheets API "
                    "can't read. Open it in Google Sheets, use File → Save as Google Sheets, and connect the "
                    "converted sheet instead.",
                )
            return (
                False,
                "Google Sheets could not open this spreadsheet. Please check the URL and that it is shared "
                "with our service account as described at https://posthog.com/docs/cdp/sources/google-sheets",
            )
        except (google_auth_exceptions.RefreshError, google_auth_exceptions.TransportError):
            # A transient failure fetching the service-account OAuth token (Google's token endpoint
            # 5xx-ing) surfaces here rather than as a gspread APIError. Its str() is a raw server
            # message like "A server error occurred." with nothing for the user to act on.
            return (
                False,
                "PostHog couldn't verify access to your Google Sheet right now because Google returned a "
                "temporary error. Please try again in a moment.",
            )
        except Exception as e:
            return False, str(e)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_SHEETS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Google Sheets",
            caption="Ensure you have granted PostHog access to your Google Sheet as instructed in the [documentation](https://posthog.com/docs/cdp/sources/google-sheets). The first row of each sheet must contain unique column headers, since PostHog reads it as the column names when syncing.",
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
