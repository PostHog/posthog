from typing import Optional, cast

from products.warehouse_sources.sources.livestorm._config import LivestormSourceConfig
from products.warehouse_sources.sources.livestorm.livestorm import (
    LivestormResumeConfig,
    livestorm_source,
    probe_credentials,
)
from products.warehouse_sources.sources.livestorm.settings import (
    ADMIN_READ_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    OPT_IN_ENDPOINTS,
)
from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
    detect,
)


@SourceRegistry.register
class LivestormSource(ResumableSource[LivestormSourceConfig, LivestormResumeConfig]):
    codebase_detection = detect(env=("^LIVESTORM_",), script_hosts=("app.livestorm.co",))

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://developers.livestorm.co/reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LIVESTORM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LIVESTORM,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Livestorm",
            caption="""Sync your Livestorm event, session, and workspace data into PostHog.

Create an API token in Livestorm under **Account settings > Integrations > Public API**. Give it **Admin** read access for `team_members` and `people_attributes`. Give it **Events** read access for the other tables.

Livestorm allows 10,000 API calls per 30 days for each account. `session_people`, `session_chat_messages`, and `session_questions` each make at least one request per session on every sync. Sync these tables less often or deselect them if you have many sessions.""",
            iconPath="/static/services/livestorm.png",
            docsUrl="https://posthog.com/docs/cdp/sources/livestorm",
            releaseStatus=ReleaseStatus.BETA,
            keywords=["webinar"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.livestorm.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Livestorm rejected the API token. Create a new token in Livestorm, then reconnect the source.",
            "403 Client Error: Forbidden for url": "The Livestorm API token does not have access to this table. Check the Events scope, or the Admin scope for team_members and people_attributes, then reconnect the source.",
        }

    def get_retry_exhausted_errors(self) -> dict[str, str]:
        # Livestorm answers 429 once the account's 30-day quota of 10,000 calls is spent. The error
        # stays retryable so syncs resume by themselves after the quota resets.
        return {
            "HTTP 429 for https://api.livestorm.co": "Livestorm's API quota for this account is used up. It allows 10,000 calls per 30 days, shared with your other Livestorm integrations. Syncs resume after the quota resets. Sync less often, deselect tables that read every session, or ask Livestorm for a higher quota.",
        }

    def get_schemas(
        self,
        config: LivestormSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            descriptions=dict.fromkeys(ADMIN_READ_ENDPOINTS, "Requires Admin read access in Livestorm."),
            should_sync_default=dict.fromkeys(OPT_IN_ENDPOINTS, False),
        )

    def validate_credentials(
        self,
        config: LivestormSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        probe_endpoint = schema_name
        if schema_name is not None and schema_name not in ADMIN_READ_ENDPOINTS:
            probe_endpoint = "events"
        is_valid, status = probe_credentials(config.api_token, probe_endpoint)
        if is_valid:
            return True, None
        if status == 401:
            return False, "Livestorm rejected the API token. Check that you pasted the whole token."
        if status == 403:
            if schema_name is None:
                return False, "Livestorm blocked access to this workspace. Contact Livestorm support."
            if probe_endpoint in ADMIN_READ_ENDPOINTS:
                return False, "The API token has no read access to this table. Give it read access to the Admin scope."
            return False, "The API token has no read access to events. Give it read access to the Events scope."
        return False, "Couldn't reach Livestorm with this token. Check the token, then try again."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LivestormResumeConfig]:
        return ResumableSourceManager[LivestormResumeConfig](inputs, LivestormResumeConfig)

    def source_for_pipeline(
        self,
        config: LivestormSourceConfig,
        resumable_source_manager: ResumableSourceManager[LivestormResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return livestorm_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
