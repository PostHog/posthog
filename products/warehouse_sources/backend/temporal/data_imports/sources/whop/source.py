from typing import TYPE_CHECKING, Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.whop import WhopSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.whop import whop as api_client
from products.warehouse_sources.backend.temporal.data_imports.sources.whop.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MERGE_ONLY_ENDPOINTS,
    RESOURCE_TO_EVENT_PREFIX,
    SCHEMA_TO_WEBHOOK_EVENTS,
    WEBHOOK_SCHEMA_NAMES,
    WHOP_API_KEYS_URL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.whop.whop import WhopResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC


@SourceRegistry.register
class WhopSource(
    ResumableSource[WhopSourceConfig, WhopResumeConfig],
    WebhookSource[WhopSourceConfig],
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Whop's dated `Api-Version-Date` header pins the Experimental API. The stable `/api/v1`
    # endpoints this source calls are served on the unversioned contract when the header is omitted,
    # so no version is sent and none is declared.
    api_docs_url = "https://docs.whop.com/developer/api/versioning"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WHOP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WHOP,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Whop",
            caption=(
                "Connect your Whop company to sync payments, memberships, members, products, promo codes, "
                "invoices, refunds, and disputes into PostHog. Create a company API key in the "
                f"[Developer tab]({WHOP_API_KEYS_URL}) of your Whop dashboard."
            ),
            iconPath="/static/services/whop.png",
            docsUrl="https://posthog.com/docs/cdp/sources/whop",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        caption=(
                            f"Create a company API key in the [Developer tab]({WHOP_API_KEYS_URL}) of your Whop "
                            "dashboard. Grant it read access to the resources you want to sync: "
                            "`company:basic:read`, `member:basic:read`, `payment:basic:read`, "
                            "`access_pass:basic:read`, `plan:basic:read`, `promo_code:basic:read` and "
                            "`invoice:basic:read`, plus `developer:manage_webhook` if you want PostHog to "
                            "register the webhook for you."
                        ),
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="company_id",
                        label="Company ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="biz_xxxxxxxxxxxxxx",
                        caption="The ID of the Whop company to sync, shown in your Whop dashboard URL.",
                        secret=False,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
            webhookSetupCaption=(
                "PostHog tries to register a Whop webhook for you using your API key, which needs the "
                "`developer:manage_webhook` permission.\n\n"
                "**Manual setup** (only needed if automatic registration failed):\n\n"
                f"1. Go to the [Developer tab]({WHOP_API_KEYS_URL}) in your Whop dashboard\n"
                "2. Click **Create Webhook** and paste the webhook URL shown below\n"
                "3. Set the API version to **v1**\n"
                "4. Select the payment, membership, member, product, entry, invoice, refund, dispute, "
                "setup intent, and shipment events matching the tables you sync\n"
                "5. Copy the webhook secret into the field below so PostHog can verify deliveries"
            ),
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_secret",
                        label="Signing secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        caption=(
                            "The webhook secret shown in your Whop dashboard. PostHog uses it to verify the "
                            "webhook-signature header on every delivery."
                        ),
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.whop.com": (
                "Whop rejected the API key. Create a new company API key in your Whop dashboard and reconnect."
            ),
            "403 Client Error: Forbidden for url: https://api.whop.com": (
                "Your Whop API key does not have permission to read this resource. Grant the missing read "
                "permission in your Whop dashboard and reconnect."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.whop.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: WhopSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Endpoints with no `created_at` sort option page newest-first and stop at the watermark,
        # which re-yields boundary rows that only a merge on `id` can dedupe.
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            merge_only=MERGE_ONLY_ENDPOINTS,
            supports_webhooks=WEBHOOK_SCHEMA_NAMES,
        )

    def validate_credentials(
        self,
        config: WhopSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.company_id.startswith("biz_"):
            return False, "Whop company IDs start with `biz_`. Copy the ID from your Whop dashboard URL."

        is_valid, status = api_client.validate_credentials(config.api_key, config.company_id)
        if is_valid:
            return True, None
        # A 403 means the key is genuine but lacks `company:basic:read`. Users may deliberately grant
        # only the permissions for the tables they sync, so don't block source creation on it.
        if status == 403 and schema_name is None:
            return True, None
        if status == 404:
            return False, "Whop could not find that company. Check the company ID and try again."
        return False, "Invalid Whop API key or company ID."

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.whop.webhook_template import template

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return RESOURCE_TO_EVENT_PREFIX

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WhopResumeConfig]:
        return ResumableSourceManager[WhopResumeConfig](inputs, WhopResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(
        self, config: WhopSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookCreationResult:
        return api_client.create_webhook(config.api_key, config.company_id, webhook_url)

    def get_desired_webhook_events(
        self, config: WhopSourceConfig, eligible_schema_names: list[str]
    ) -> list[str] | None:
        return sorted({event for name in eligible_schema_names for event in SCHEMA_TO_WEBHOOK_EVENTS.get(name, [])})

    def sync_webhook_events(
        self,
        config: WhopSourceConfig,
        webhook_url: str,
        team_id: int,
        eligible_schema_names: list[str],
        api_version: str | None = None,
    ) -> WebhookSyncResult:
        desired_events = self.get_desired_webhook_events(config, eligible_schema_names) or []
        return api_client.sync_webhook_events(config.api_key, config.company_id, webhook_url, desired_events)

    def get_external_webhook_info(
        self, config: WhopSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> ExternalWebhookInfo | None:
        return api_client.get_external_webhook_info(config.api_key, config.company_id, webhook_url)

    def delete_webhook(
        self, config: WhopSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookDeletionResult:
        return api_client.delete_webhook(config.api_key, config.company_id, webhook_url)

    def source_for_pipeline(
        self,
        config: WhopSourceConfig,
        resumable_source_manager: ResumableSourceManager[WhopResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return api_client.whop_source(
            api_key=config.api_key,
            company_id=config.company_id,
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
