from typing import Optional, cast

from posthog.models.integration import OauthIntegration

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import CursorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.member_accounts import (
    ALL_ACCOUNTS_UNREADABLE,
    member_account_rows,
    member_integrations,
    readable_member_accounts,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googlecalendar import (
    GoogleCalendarSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_calendar.google_calendar import (
    GoogleCalendarCursor,
    accounts_source,
    events_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_calendar.settings import (
    ACCOUNTS,
    ENDPOINTS,
    EVENTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

GOOGLE_CALENDAR_INTEGRATION_KIND = "google-calendar"
APP_NOT_CONFIGURED = "Google Calendar is not set up on this PostHog instance."


@SourceRegistry.register
class GoogleCalendarSource(SimpleSource[GoogleCalendarSourceConfig], CursorSource[GoogleCalendarCursor]):
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://developers.google.com/workspace/calendar/api/v3/reference"

    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLECALENDAR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLECALENDAR,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            keywords=["meetings", "gcal"],
            label="Google Calendar",
            releaseStatus=ReleaseStatus.ALPHA,
            featureFlag="dwh-google-calendar",
            caption=(
                "Sync the meetings of every teammate who connects their Google account.\n\n"
                "This source has no credentials of its own. After you create it, each teammate opens its "
                "**Configuration** tab and connects their own account. Google accounts that are already "
                "connected to this project for calendar sync are included.\n\n"
                "Meeting titles, descriptions and attendee addresses are not synced."
            ),
            iconPath="/static/services/google_calendar.png",
            memberIntegrationKind=GOOGLE_CALENDAR_INTEGRATION_KIND,
            fields=cast(list[FieldType], []),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.google_calendar.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            ALL_ACCOUNTS_UNREADABLE: (
                "None of the connected Google accounts could be read. Ask each person to reconnect their "
                "account from this source's Configuration tab."
            ),
            "Google Calendar app not configured": APP_NOT_CONFIGURED,
        }

    def get_schemas(
        self,
        config: GoogleCalendarSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Merge only, because a run that fails before its cursor is stored reads the same events again.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=[EVENTS])

    def validate_credentials(
        self,
        config: GoogleCalendarSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # Teammates connect their accounts after the source exists, so only the OAuth app can be checked.
        try:
            OauthIntegration.oauth_config_for_kind(GOOGLE_CALENDAR_INTEGRATION_KIND)
        except NotImplementedError:
            return False, APP_NOT_CONFIGURED
        return True, None

    def cursor_class(self) -> type[GoogleCalendarCursor]:
        return GoogleCalendarCursor

    def merge_cursors(self, current: GoogleCalendarCursor, candidate: GoogleCalendarCursor) -> GoogleCalendarCursor:
        # A run stages only the accounts it read. The other accounts keep their position.
        return GoogleCalendarCursor(
            updated_at=_newest(current.updated_at, candidate.updated_at),
            synced_until=_newest(current.synced_until, candidate.synced_until),
        )

    def source_for_pipeline(self, config: GoogleCalendarSourceConfig, inputs: SourceInputs) -> SourceResponse:
        integrations = member_integrations(inputs.team_id, GOOGLE_CALENDAR_INTEGRATION_KIND)

        if inputs.schema_name == ACCOUNTS:
            return accounts_source(member_account_rows(integrations))

        if inputs.schema_name != EVENTS:
            raise ValueError(f"Unknown Google Calendar table: {inputs.schema_name}")

        manager = self.get_cursor_manager(inputs)
        return events_source(
            accounts=readable_member_accounts(integrations, inputs.logger),
            # A full refresh rebuilds the table, so it reads every account from the start of its window.
            cursor=manager.load() if inputs.should_use_incremental_field else None,
            stage_cursor=manager.stage,
            logger=inputs.logger,
        )


def _newest(current: dict[str, str], candidate: dict[str, str]) -> dict[str, str]:
    merged = dict(current)
    for account_id, value in candidate.items():
        merged[account_id] = max(value, merged.get(account_id, value))
    return merged
