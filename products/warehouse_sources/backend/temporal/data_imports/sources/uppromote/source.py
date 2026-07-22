from typing import TYPE_CHECKING, Optional, cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.uppromote import (
    UpPromoteSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uppromote.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    RESOURCE_TO_UPPROMOTE_OBJECT_TYPE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uppromote.uppromote import (
    UpPromoteResumeConfig,
    all_desired_webhook_events,
    create_webhook as create_uppromote_webhook,
    delete_webhook as delete_uppromote_webhook,
    get_external_webhook_info as get_uppromote_webhook_info,
    sync_webhook_events as sync_uppromote_webhook_events,
    uppromote_source,
    validate_credentials as validate_uppromote_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC


@SourceRegistry.register
class UpPromoteSource(
    ResumableSource[UpPromoteSourceConfig, UpPromoteResumeConfig],
    WebhookSource[UpPromoteSourceConfig],
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://aff-api.uppromote.com/docs/v2/api-overview-1615961m0"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.UPPROMOTE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.UP_PROMOTE,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="UpPromote",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Enter your UpPromote API key to pull your affiliate programs, affiliates, "
                "referrals, coupons, and payments into the PostHog Data warehouse.\n\n"
                "You can create an API key in the UpPromote app under **Settings** > "
                "**Integrations** > **API Key** (available on the Professional plan and above)."
            ),
            iconPath="/static/services/uppromote.png",
            docsUrl="https://posthog.com/docs/cdp/sources/uppromote",
            keywords=["affiliate", "referral", "shopify"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="UpPromote API key",
                        secret=True,
                    ),
                ],
            ),
            webhookSetupCaption=(
                "PostHog subscribes to UpPromote's referral, affiliate, and payment webhook "
                "events for you using your API key, including the signing secret — no manual "
                "steps needed.\n\n"
                "**Manual setup** (only needed if auto-registration failed, e.g. an event is "
                "already subscribed to another URL — UpPromote allows one subscription per "
                "event):\n\n"
                "1. Subscribe the webhook URL shown below to the events you want via "
                "UpPromote's `POST /webhook-subscriptions` API endpoint\n"
                "2. In UpPromote, go to **Settings** > **Integrations** > **Get Secret Key**\n"
                "3. Copy the secret key into the field below"
            ),
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_secret",
                        label="Signing secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="UpPromote webhook secret key",
                        secret=True,
                    ),
                ],
            ),
        )

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.uppromote.webhook_template import template

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return RESOURCE_TO_UPPROMOTE_OBJECT_TYPE

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.uppromote.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://aff-api.uppromote.com": (
                "Your UpPromote API key is invalid or has been revoked. Create a new API key in "
                "the UpPromote app under Settings > Integrations > API Key, then reconnect."
            ),
            "403 Client Error: Forbidden for url: https://aff-api.uppromote.com": (
                "UpPromote rejected your API key. The API requires the Professional plan or "
                "above — check your plan and API key, then reconnect."
            ),
        }

    def get_schemas(
        self,
        config: UpPromoteSourceConfig,
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
            # Rows on every windowed endpoint are mutable (referral/affiliate statuses and
            # amounts change), so merge is the only safe incremental disposition.
            merge_only=ENDPOINTS,
            supports_webhooks=tuple(RESOURCE_TO_UPPROMOTE_OBJECT_TYPE.keys()),
            descriptions={
                "payments_unpaid": (
                    "Outstanding (approved but unpaid) commission per affiliate. An aggregated "
                    "snapshot, refreshed in full on every sync"
                ),
            },
        )

    def validate_credentials(
        self,
        config: UpPromoteSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        valid, error = validate_uppromote_credentials(config.api_key)
        if valid:
            return True, None
        return False, error or "Invalid UpPromote API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[UpPromoteResumeConfig]:
        return ResumableSourceManager[UpPromoteResumeConfig](inputs, UpPromoteResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(
        self, config: UpPromoteSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookCreationResult:
        return create_uppromote_webhook(config.api_key, webhook_url)

    def get_desired_webhook_events(
        self, config: UpPromoteSourceConfig, eligible_schema_names: list[str]
    ) -> list[str] | None:
        # Every mappable event, not just the selected tables — auto-heals subscriptions created
        # before a table was enabled; unmapped payloads are dropped by the hog function.
        return all_desired_webhook_events()

    def sync_webhook_events(
        self,
        config: UpPromoteSourceConfig,
        webhook_url: str,
        team_id: int,
        eligible_schema_names: list[str],
        api_version: str | None = None,
    ) -> WebhookSyncResult:
        desired_events = self.get_desired_webhook_events(config, eligible_schema_names) or []
        return sync_uppromote_webhook_events(config.api_key, webhook_url, desired_events)

    def get_external_webhook_info(
        self, config: UpPromoteSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> ExternalWebhookInfo | None:
        return get_uppromote_webhook_info(config.api_key, webhook_url)

    def delete_webhook(
        self, config: UpPromoteSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookDeletionResult:
        return delete_uppromote_webhook(config.api_key, webhook_url)

    def source_for_pipeline(
        self,
        config: UpPromoteSourceConfig,
        resumable_source_manager: ResumableSourceManager[UpPromoteResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return uppromote_source(
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
