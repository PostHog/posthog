from typing import TYPE_CHECKING, Optional, cast

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

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    FieldType,
    ResumableSource,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSource,
    WebhookSyncResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sparkpost import (
    SparkPostSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost import sparkpost as api_client
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LIMITED_RETENTION_ENDPOINTS,
    SPARKPOST_ENDPOINTS,
    WEBHOOK_EVENT_TYPES,
    WEBHOOK_RESOURCE_MAP,
    WEBHOOK_SCHEMA_NAMES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.sparkpost import (
    SparkPostResumeConfig,
    sparkpost_source,
    validate_credentials as validate_sparkpost_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC


@SourceRegistry.register
class SparkPostSource(
    ResumableSource[SparkPostSourceConfig, SparkPostResumeConfig],
    WebhookSource[SparkPostSourceConfig],
):
    api_docs_url = "https://developers.sparkpost.com/api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SPARKPOST

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key is sent to the host derived from `region`, so changing the region must
        # re-require the key rather than reusing it against a different host.
        return ["region"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SPARK_POST,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="SparkPost",
            releaseStatus=ReleaseStatus.ALPHA,
            # Kept hidden for now: the implementation follows the public SparkPost docs but its
            # end-to-end sync behaviour hasn't been exercised against a live account yet.
            caption="""Connect your SparkPost account to sync message events, suppression lists, recipient lists, templates, sending domains, subaccounts, and webhooks into the PostHog Data warehouse.

Create an API key in your [SparkPost account settings](https://app.sparkpost.com/account/api-keys) (or the EU console at app.eu.sparkpost.com). Grant the read permissions for the data you want to sync, for example:
- `Events: Read-only`
- `Suppression Lists: Read-only`
- `Recipient Lists: Read-only`
- `Templates: Read-only`
- `Sending Domains: Read-only`
- `Subaccounts: Read-only`
- `Webhooks: Read-only`

SparkPost runs independent US and EU stacks that do not share data — pick the region your account is on. Message events are retained for 10 days, so the initial sync of events can only reach back that far.""",
            iconPath="/static/services/sparkpost.png",
            docsUrl="https://posthog.com/docs/cdp/sources/sparkpost",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.sparkpost.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api.eu.sparkpost.com)", value="eu"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="SparkPost API key",
                        secret=True,
                    ),
                ],
            ),
            webhookSetupCaption=(
                "PostHog registers an event webhook on your SparkPost account and subscribes it to the "
                "message events the Events API also returns, so pushed events land in the same table as "
                "the backfill. The API key needs the `Webhooks: Read/Write` permission.\n\n"
                "Because SparkPost only keeps message events for 10 days, the webhook is the only way to "
                "keep them for longer.\n\n"
                "**Manual setup** (only needed if automatic registration failed):\n\n"
                "1. Go to **Webhooks** in your SparkPost account and create a webhook pointing at the URL "
                "shown below\n"
                "2. Subscribe it to the message events you want, for example `delivery`, `bounce`, `open` "
                "and `click`\n"
                "3. Set authentication to **Basic auth** and choose a username and password\n\n"
                "Then paste the matching `Basic ...` header value into the field below so PostHog can "
                "verify each delivery."
            ),
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="authorization_header",
                        label="Authorization header value",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Basic dXNlcjpwYXNz",
                        caption=(
                            "The exact value SparkPost sends in the Authorization header. PostHog fills "
                            "this in when it registers the webhook for you."
                        ),
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid SparkPost API key. Generate a valid key and reconnect.",
            "403 Client Error": "Your SparkPost API key is missing the read permissions for this data. Grant the required permissions and reconnect.",
        }

    def get_schemas(
        self,
        config: SparkPostSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=SPARKPOST_ENDPOINTS[endpoint].supports_incremental,
                supports_append=SPARKPOST_ENDPOINTS[endpoint].supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=SPARKPOST_ENDPOINTS[endpoint].should_sync_default,
                supports_webhooks=endpoint in WEBHOOK_SCHEMA_NAMES,
                description=(
                    "Only the last 10 days are available on initial sync (SparkPost event retention)"
                    if endpoint in LIMITED_RETENTION_ENDPOINTS
                    else None
                ),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: SparkPostSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_sparkpost_credentials(config.region, config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SparkPostResumeConfig]:
        return ResumableSourceManager[SparkPostResumeConfig](inputs, SparkPostResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.webhook_template import (  # noqa: PLC0415
            template,
        )

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return WEBHOOK_RESOURCE_MAP

    def create_webhook(
        self, config: SparkPostSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookCreationResult:
        return api_client.create_webhook(config.region, config.api_key, webhook_url)

    def get_desired_webhook_events(
        self, config: SparkPostSourceConfig, eligible_schema_names: list[str]
    ) -> list[str] | None:
        if not any(name in WEBHOOK_SCHEMA_NAMES for name in eligible_schema_names):
            return []
        return list(WEBHOOK_EVENT_TYPES)

    def sync_webhook_events(
        self,
        config: SparkPostSourceConfig,
        webhook_url: str,
        team_id: int,
        eligible_schema_names: list[str],
        api_version: str | None = None,
    ) -> WebhookSyncResult:
        desired_events = self.get_desired_webhook_events(config, eligible_schema_names) or []
        return api_client.sync_webhook_events(config.region, config.api_key, webhook_url, desired_events)

    def get_external_webhook_info(
        self, config: SparkPostSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> ExternalWebhookInfo | None:
        return api_client.get_external_webhook_info(config.region, config.api_key, webhook_url)

    def delete_webhook(
        self, config: SparkPostSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookDeletionResult:
        return api_client.delete_webhook(config.region, config.api_key, webhook_url)

    def source_for_pipeline(
        self,
        config: SparkPostSourceConfig,
        resumable_source_manager: ResumableSourceManager[SparkPostResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return sparkpost_source(
            region=config.region,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            webhook_source_manager=self.get_webhook_source_manager(inputs),
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
