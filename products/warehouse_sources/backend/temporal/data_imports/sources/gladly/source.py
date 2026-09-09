from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gladly import GladlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.gladly import (
    GladlyResumeConfig,
    gladly_source,
    validate_credentials as validate_gladly_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    REPORT_ENDPOINTS,
    REPORT_INCREMENTAL_LOOKBACK_SECONDS,
    SHOULD_SYNC_DEFAULT,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GladlySource(ResumableSource[GladlySourceConfig, GladlyResumeConfig]):
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://developer.gladly.com"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GLADLY

    @property
    def connection_host_fields(self) -> list[str]:
        # `organization` and `domain` together determine the host the stored token is
        # sent to; retargeting either must re-require the token.
        return ["organization", "domain"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Gladly authentication failed. Please check your agent email and API token.",
            "403 Client Error: Forbidden for url": "Gladly denied access. Please check that the agent has the API User permission.",
            # Raised by `_report_rows` when a report header is missing the columns the stream is
            # keyed on. Gladly returns the same body for that window on a retry, so stop and tell
            # the customer rather than replaying it.
            "Gladly report is missing required columns": (
                "Gladly returned a report without the columns this table syncs on, so there was no "
                "data to sync. Re-enable the sync to try again, and contact support if it keeps happening."
            ),
        }

    def get_retryable_errors(self) -> set[str]:
        # `_report_rows` streams the report CSV while it yields rows (see gladly.py), so a stall in
        # Gladly's report generation past REQUEST_TIMEOUT_SECONDS raises the bare urllib3
        # read-timeout mid-stream, after `generate_report`'s own retry-on-`requests.ReadTimeout` has
        # already returned a response, so it isn't caught there either. Temporal's activity retry
        # regenerates the report and re-streams it; the resumable window state means only the
        # in-flight window is redone, deduped on merge, so this is self-recovering rather than a
        # tracked-exception-worthy failure.
        return {"Read timed out"}

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GLADLY,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Gladly",
            caption="""Connect your Gladly account to pull your customer service data into the PostHog Data warehouse.

Your organization is the part of your Gladly URL before `.gladly.com`. For `myorg.gladly.com` enter `myorg`, and for `myorg.us-1.gladly.com` enter `myorg.us-1`. The API token must belong to an agent with the API User permission (Settings > API Tokens). Leave the domain on Production unless you are connecting a Gladly sandbox, which is served on `gladly.qa`. Data comes from Gladly's scheduled export jobs, which retain files for 14 days. History older than that requires asking Gladly support to regenerate exports. The conversations table is built from Gladly's Conversation Export report instead, so it is not limited to the 14-day export window, and the conversation and contact timestamps tables come from Gladly's reports as well, reaching back 90 days on their first sync.""",
            iconPath="/static/services/gladly.png",
            docsUrl="https://posthog.com/docs/cdp/sources/gladly",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="organization",
                        label="Organization",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="myorg",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="agent_email",
                        label="Agent email",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=True,
                        placeholder="agent@company.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="domain",
                        label="Gladly domain",
                        required=True,
                        defaultValue="gladly.com",
                        options=[
                            SourceFieldSelectConfigOption(label="Production (gladly.com)", value="gladly.com"),
                            SourceFieldSelectConfigOption(label="Sandbox (gladly.qa)", value="gladly.qa"),
                        ],
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: GladlySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Report windows are re-read on resume and behind the watermark, so
        # appending would duplicate rows (merge_only). The event-grain report
        # tables are high-volume, so they start opt-in (should_sync_default).
        schemas = build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            merge_only=REPORT_ENDPOINTS,
            should_sync_default=SHOULD_SYNC_DEFAULT,
        )
        # Conversation-report rows restate in place as records change, so its
        # incremental runs re-read a trailing window to catch the restatements.
        for schema in schemas:
            if schema.name == "conversations":
                schema.default_incremental_lookback_seconds = REPORT_INCREMENTAL_LOOKBACK_SECONDS
        return schemas

    def validate_credentials(
        self,
        config: GladlySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_gladly_credentials(config.organization, config.agent_email, config.api_token, config.domain)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GladlyResumeConfig]:
        return ResumableSourceManager[GladlyResumeConfig](inputs, GladlyResumeConfig)

    def source_for_pipeline(
        self,
        config: GladlySourceConfig,
        resumable_source_manager: ResumableSourceManager[GladlyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return gladly_source(
            organization=config.organization,
            agent_email=config.agent_email,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            domain=config.domain,
        )
