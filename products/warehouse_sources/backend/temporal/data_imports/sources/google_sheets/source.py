from typing import Optional, cast

from django.conf import settings

import gspread
from google.auth.exceptions import RefreshError

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
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
class GoogleSheetsSource(SimpleSource[GoogleSheetsSourceConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLESHEETS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "the header row in the worksheet contains duplicates": "Import failed: There exists duplicate column headers. Please make sure all column headers have values and aren't duplicated.",
            "can't be found": None,
            "SpreadsheetNotFound": None,
            "must be real number, not str": "Import failed: a numeric column contains a non-numeric value. Ensure every cell in numeric columns is stored as a plain number.",
            "Spreadsheet access denied": "Import failed: PostHog does not have access to this spreadsheet. Please share it with our service account as described at https://posthog.com/docs/cdp/sources/google-sheets",
            # OAuth path: sharing with the service account wouldn't help — the connected account itself
            # lacks access. Tell the user to reconnect or have the owner share it with that account.
            "connected Google account can't access this spreadsheet": "Import failed: the connected Google account can't access this spreadsheet. Reconnect the account, or have the sheet's owner share it with that account.",
            # gspread raises APIError "[404]: Requested entity was not found." when the
            # spreadsheet has been deleted or is otherwise unreachable. Retrying cannot recover.
            "Requested entity was not found": "Import failed: the Google Sheet could not be found. It may have been deleted or moved. Please check the spreadsheet URL and that it is shared with our service account.",
            # OAuth auth failures: the stored refresh token has been revoked/expired, or its consent
            # is missing the Sheets scope. google-auth raises these while refreshing the access token
            # — retrying can't recover, so ask the user to reconnect.
            "invalid_grant": "Import failed: your Google account connection has expired or been revoked. Please reconnect it.",
            "invalid_scope": "Import failed: your Google account connection is missing the required Sheets permission. Please reconnect it.",
            # Instance misconfiguration (service account env vars unset) — retrying can't fix it.
            "Google Sheets service account is not configured": "Import failed: PostHog's Google Sheets service account isn't configured on this instance. Connect a Google account instead, or ask your administrator to configure it.",
        }

    def get_schemas(
        self,
        config: GoogleSheetsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        sheets = get_google_sheets_schemas(config, team_id)

        if names is not None:
            names_set = set(names)
            sheets = [(name, row_count) for name, row_count in sheets if name in names_set]

        schemas: list[SourceSchema] = []
        for name, _ in sheets:
            incremental_fields = get_google_sheets_schema_incremental_fields(config, team_id, name)

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
            inputs.team_id,
            inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    def validate_credentials(
        self, config: GoogleSheetsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        integration_id = config.auth_method.google_sheets_integration_id if config.auth_method else None
        if integration_id:
            try:
                self.get_oauth_integration(integration_id, team_id)
            except ValueError:
                return (
                    False,
                    "The Google account connected to this source no longer exists. Please reconnect your Google account.",
                )

        try:
            client = google_sheets_client(integration_id, team_id)
            client.open_by_url(config.spreadsheet_url)
            return True, None
        except gspread.SpreadsheetNotFound:
            return False, "Spreadsheet not found at URL provided"
        except PermissionError:
            if integration_id:
                return (
                    False,
                    "The connected Google account can't access this spreadsheet. Open it with that account, "
                    "or have the owner share it, then try again.",
                )
            return (
                False,
                "Permissions missing from spreadsheet. View documentation at https://posthog.com/docs/cdp/sources/google-sheets",
            )
        except RefreshError:
            return (
                False,
                "PostHog couldn't authenticate with your Google account. Please reconnect it and try again.",
            )
        except Exception as e:
            return False, str(e)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_SHEETS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Google Sheets",
            caption="Connect a Google account to sync only the sheets that account can access, or share a sheet with PostHog's service account. See the [documentation](https://posthog.com/docs/cdp/sources/google-sheets).",
            releaseStatus=ReleaseStatus.GA,
            iconPath="/static/services/Google_Sheets.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/google-sheets",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        # required=False so the generated `auth_method` carries a default: existing
                        # sources predate this field, and config validation on update must not reject
                        # a stored config that has no `auth_method` yet.
                        name="auth_method",
                        label="Authentication method",
                        required=False,
                        defaultValue="service_account",
                        # Gated during rollout: until the flag is on, the form shows only the
                        # spreadsheet URL field (no selector), so existing users see no change.
                        featureFlag="dwh-google-sheets-oauth",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="Share with PostHog's service account",
                                value="service_account",
                                fields=None,
                            ),
                            SourceFieldSelectConfigOption(
                                label="Connect a Google account",
                                value="oauth",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldOauthConfig(
                                            # required=False so legacy configs (and the
                                            # service-account option) hydrate with a null
                                            # integration_id; the runtime keys off its presence.
                                            name="google_sheets_integration_id",
                                            label="Google account",
                                            required=False,
                                            kind="google-sheets",
                                            requiredScopes="https://www.googleapis.com/auth/spreadsheets",
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="spreadsheet_url",
                        label="Spreadsheet URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        caption=f'Paste the full Google Sheet URL. For the shared service account method, first share the sheet with **{settings.GOOGLE_SHEETS_SERVICE_ACCOUNT_CLIENT_EMAIL}** ("Viewer" is enough).',
                        # A sheet URL is not a credential, so it isn't redacted from API responses.
                        secret=False,
                    ),
                ],
            ),
            featured=True,
        )
