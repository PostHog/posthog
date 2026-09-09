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
from products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall import fourthwall as api_client
from products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall.fourthwall import (
    FourthwallResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall.settings import (
    ENDPOINTS,
    INCREMENTAL_ENDPOINTS,
    INCREMENTAL_FIELDS,
    SCHEMA_TO_WEBHOOK_EVENTS,
    SCHEMA_TO_WEBHOOK_RESOURCE,
    WEBHOOK_SCHEMA_NAMES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fourthwall import (
    FourthwallSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

DEVELOPER_SETTINGS_HELP = (
    "In your Fourthwall dashboard go to **Settings > For developers > Open API** and choose "
    "**Create API User**. Only a shop super admin can do this."
)


@SourceRegistry.register
class FourthwallSource(
    ResumableSource[FourthwallSourceConfig, FourthwallResumeConfig],
    WebhookSource[FourthwallSourceConfig],
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Every Open API path is served under `/open-api/v1.0`, which is what this source calls.
    supported_versions = ("v1.0",)
    default_version = "v1.0"
    api_docs_url = "https://docs.fourthwall.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FOURTHWALL

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall.webhook_template import (  # noqa: PLC0415
            template,
        )

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return SCHEMA_TO_WEBHOOK_RESOURCE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": (
                "Fourthwall rejected the API user. Recreate it under Settings > For developers and reconnect."
            ),
            "403 Client Error": (
                "This Fourthwall API user is not allowed to read that data. "
                "Recreate it under Settings > For developers and reconnect."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: FourthwallSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Orders are merge-only: `updatedAt` moves when an order changes status, so append mode
        # would add a second row per update instead of upserting the one order.
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            merge_only=INCREMENTAL_ENDPOINTS,
            supports_webhooks=WEBHOOK_SCHEMA_NAMES,
        )

    def validate_credentials(
        self,
        config: FourthwallSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return api_client.validate_credentials(config.username, config.password, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FourthwallResumeConfig]:
        return ResumableSourceManager[FourthwallResumeConfig](inputs, FourthwallResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(
        self, config: FourthwallSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookCreationResult:
        return api_client.create_webhook(
            config.username, config.password, self.resolve_api_version(api_version), webhook_url
        )

    def get_desired_webhook_events(
        self, config: FourthwallSourceConfig, eligible_schema_names: list[str]
    ) -> list[str] | None:
        return sorted({event for name in eligible_schema_names for event in SCHEMA_TO_WEBHOOK_EVENTS.get(name, [])})

    def sync_webhook_events(
        self,
        config: FourthwallSourceConfig,
        webhook_url: str,
        team_id: int,
        eligible_schema_names: list[str],
        api_version: str | None = None,
    ) -> WebhookSyncResult:
        desired_events = self.get_desired_webhook_events(config, eligible_schema_names) or []
        return api_client.sync_webhook_events(
            config.username, config.password, self.resolve_api_version(api_version), webhook_url, desired_events
        )

    def get_external_webhook_info(
        self, config: FourthwallSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> ExternalWebhookInfo | None:
        return api_client.get_external_webhook_info(
            config.username, config.password, self.resolve_api_version(api_version), webhook_url
        )

    def delete_webhook(
        self, config: FourthwallSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookDeletionResult:
        return api_client.delete_webhook(
            config.username, config.password, self.resolve_api_version(api_version), webhook_url
        )

    def source_for_pipeline(
        self,
        config: FourthwallSourceConfig,
        resumable_source_manager: ResumableSourceManager[FourthwallResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return api_client.fourthwall_source(
            username=config.username,
            password=config.password,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
            webhook_source_manager=self.get_webhook_source_manager(inputs),
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FOURTHWALL,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Fourthwall",
            caption=(
                "Sync your Fourthwall shop's orders, products, product templates, collections, "
                "donations, members, membership tiers, promotions and mailing list into PostHog.\n\n"
                f"{DEVELOPER_SETTINGS_HELP}"
            ),
            keywords=["merch", "memberships", "creator commerce"],
            docsUrl="https://posthog.com/docs/cdp/sources/fourthwall",
            iconPath="/static/services/fourthwall.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="username",
                        label="API user username",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        caption=DEVELOPER_SETTINGS_HELP,
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="password",
                        label="API user password",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
            webhookSetupCaption=(
                "PostHog tries to register a webhook on your shop using the API user above, "
                "subscribed to the order, donation and membership events.\n\n"
                "**Manual setup** (only needed if automatic registration failed):\n\n"
                "1. Go to **Settings > For developers > Webhooks** in your Fourthwall dashboard\n"
                "2. Add a webhook pointing at the URL shown below\n"
                "3. Subscribe it to `ORDER_PLACED`, `ORDER_UPDATED`, `DONATION`, "
                "`SUBSCRIPTION_PURCHASED`, `SUBSCRIPTION_CHANGED` and `SUBSCRIPTION_EXPIRED`\n\n"
                "Either way, copy the secret key from that same settings page into the field below "
                "so PostHog can verify deliveries."
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
                            "Your shop's webhook secret key, from Settings > For developers. PostHog "
                            "uses it to verify the X-Fourthwall-Hmac-SHA256 header on every delivery."
                        ),
                        secret=True,
                    ),
                ],
            ),
        )
