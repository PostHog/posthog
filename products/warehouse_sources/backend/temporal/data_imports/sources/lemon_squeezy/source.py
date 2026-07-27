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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lemonsqueezy import (
    LemonSqueezySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy import lemon_squeezy as api_client
from products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.lemon_squeezy import (
    LemonSqueezyResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.settings import (
    ENDPOINTS,
    INCREMENTAL_ENDPOINTS,
    INCREMENTAL_FIELDS,
    RESOURCE_TO_JSON_API_TYPE,
    SCHEMA_TO_WEBHOOK_EVENTS,
    WEBHOOK_SCHEMA_NAMES,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

LEMON_SQUEEZY_API_SETTINGS_URL = "https://app.lemonsqueezy.com/settings/api"


@SourceRegistry.register
class LemonSqueezySource(
    ResumableSource[LemonSqueezySourceConfig, LemonSqueezyResumeConfig],
    WebhookSource[LemonSqueezySourceConfig],
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.lemonsqueezy.com/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LEMONSQUEEZY

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.webhook_template import (
            template,
        )

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return RESOURCE_TO_JSON_API_TYPE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LEMON_SQUEEZY,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Lemon Squeezy",
            caption=(
                "Connect your Lemon Squeezy account to sync stores, orders, subscriptions, "
                "customers, license keys, and more into PostHog. Create an API key under "
                f"[Settings > API]({LEMON_SQUEEZY_API_SETTINGS_URL}) in your Lemon Squeezy dashboard. "
                "Note that Lemon Squeezy API keys expire after one year, and test-mode keys return "
                "test-mode data only."
            ),
            iconPath="/static/services/lemon_squeezy.png",
            docsUrl="https://posthog.com/docs/cdp/sources/lemon-squeezy",
            keywords=["lemonsqueezy"],
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
                            f"Create an API key under [Settings > API]({LEMON_SQUEEZY_API_SETTINGS_URL}). "
                            "Keys expire after one year — you'll need to reconnect with a fresh key when it does."
                        ),
                        secret=True,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
            webhookSetupCaption=(
                "PostHog tries to register a webhook on each of your Lemon Squeezy stores using "
                "your API key, with a generated signing secret used to verify deliveries.\n\n"
                "**Manual setup** (only needed if automatic registration failed):\n\n"
                "1. Go to [Settings > Webhooks](https://app.lemonsqueezy.com/settings/webhooks) in "
                "your Lemon Squeezy dashboard\n"
                "2. Click **+** to add a webhook and paste the webhook URL shown below into the "
                "**Callback URL** field\n"
                "3. Set a **Signing secret** (6-40 characters) and paste the same value into the "
                "field below so PostHog can verify deliveries\n"
                "4. Select the order, subscription, subscription payment, and license key events "
                "matching the tables you sync\n"
                "5. Click **Save webhook**, repeating for each store you want to sync"
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
                            "The signing secret configured on the Lemon Squeezy webhook. PostHog "
                            "uses it to verify the X-Signature header on every delivery."
                        ),
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.lemonsqueezy.com": (
                "Lemon Squeezy rejected the API key. Keys expire after one year — generate a new "
                "key under Settings > API and reconnect."
            ),
            "403 Client Error: Forbidden for url: https://api.lemonsqueezy.com": (
                "Your Lemon Squeezy API key does not have access to this resource. Check the key "
                "in your Lemon Squeezy dashboard and reconnect."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: LemonSqueezySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Incremental endpoints are merge-only: the stop-early cursor re-yields watermark
        # boundary rows, which only a merge on `id` can dedupe (append would duplicate them).
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            merge_only=INCREMENTAL_ENDPOINTS,
            supports_webhooks=WEBHOOK_SCHEMA_NAMES,
        )

    def validate_credentials(
        self,
        config: LemonSqueezySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if api_client.validate_credentials(config.api_key):
            return True, None
        return False, "Invalid Lemon Squeezy API key. Note that keys expire after one year."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LemonSqueezyResumeConfig]:
        return ResumableSourceManager[LemonSqueezyResumeConfig](inputs, LemonSqueezyResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(
        self, config: LemonSqueezySourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookCreationResult:
        return api_client.create_webhook(config.api_key, webhook_url)

    def get_desired_webhook_events(
        self, config: LemonSqueezySourceConfig, eligible_schema_names: list[str]
    ) -> list[str] | None:
        return sorted({event for name in eligible_schema_names for event in SCHEMA_TO_WEBHOOK_EVENTS.get(name, [])})

    def sync_webhook_events(
        self,
        config: LemonSqueezySourceConfig,
        webhook_url: str,
        team_id: int,
        eligible_schema_names: list[str],
        api_version: str | None = None,
    ) -> WebhookSyncResult:
        desired_events = self.get_desired_webhook_events(config, eligible_schema_names) or []
        return api_client.sync_webhook_events(config.api_key, webhook_url, desired_events)

    def get_external_webhook_info(
        self, config: LemonSqueezySourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> ExternalWebhookInfo | None:
        return api_client.get_external_webhook_info(config.api_key, webhook_url)

    def delete_webhook(
        self, config: LemonSqueezySourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookDeletionResult:
        return api_client.delete_webhook(config.api_key, webhook_url)

    def source_for_pipeline(
        self,
        config: LemonSqueezySourceConfig,
        resumable_source_manager: ResumableSourceManager[LemonSqueezyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return api_client.lemon_squeezy_source(
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
