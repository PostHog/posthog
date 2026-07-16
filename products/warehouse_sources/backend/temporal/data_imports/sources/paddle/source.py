from typing import TYPE_CHECKING, Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PaddleSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.constants import RESOURCE_TO_PADDLE_ENTITY
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.paddle import (
    PaddlePermissionError,
    PaddleResumeConfig,
    create_webhook as create_paddle_webhook,
    delete_webhook as delete_paddle_webhook,
    get_external_webhook_info as get_paddle_external_webhook_info,
    paddle_source,
    update_webhook_events as update_paddle_webhook_events,
    validate_credentials as validate_paddle_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.settings import (
    ENDPOINTS as PADDLE_ENDPOINTS,
    INCREMENTAL_FIELDS as PADDLE_INCREMENTAL_FIELDS,
    PADDLE_WEBHOOK_EVENTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC


@SourceRegistry.register
class PaddleSource(
    ResumableSource[PaddleSourceConfig, PaddleResumeConfig],
    WebhookSource[PaddleSourceConfig],
):
    api_docs_url = "https://developer.paddle.com"
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    has_managed_hogql_schema = True  # canonical Paddle schema in external_table_definitions

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PADDLE

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.webhook_template import template

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return RESOURCE_TO_PADDLE_ENTITY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PADDLE,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Paddle",
            iconPath="/static/services/paddle.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="live",
                        options=[
                            SourceFieldSelectConfigOption(label="Live", value="live"),
                            SourceFieldSelectConfigOption(label="Sandbox", value="sandbox"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="paddle_api_key",
                        label="API Key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="pdl_live_...",
                        caption="The API key must belong to the selected environment: live keys start with `pdl_live_`, sandbox keys with `pdl_sdbx_`.",
                        secret=True,
                    ),
                ],
            ),
            webhookSetupCaption="""PostHog registers a notification destination in Paddle using your API key and captures its secret key automatically, so no manual steps are usually needed.

To set up the webhook manually:

1. Go to your Paddle dashboard > **Developer tools** > **Notifications**
2. Click **New destination**
3. Paste the webhook URL shown below into the **URL** field
4. Under **Events**, select the events for the entities you sync (transactions, subscriptions, customers, products, prices, discounts, adjustments)
5. Click **Save destination**

Then copy the destination's **secret key** (starts with `pdl_ntfset_`) into the field below so PostHog can verify deliveries.

If automatic creation failed due to a permissions error, your API key needs write access for notification settings. You can update this in your Paddle API key settings.""",
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_secret",
                        label="Signing secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="pdl_ntfset_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        errors: dict[str, str | None] = {}
        # Keys embed the failing host, so both environments need entries.
        for host in ("https://api.paddle.com", "https://sandbox-api.paddle.com"):
            errors[f"400 Client Error: Bad Request for url: {host}"] = (
                "Paddle rejected the request parameters. Please check your source configuration and incremental sync state, then try again."
            )
            errors[f"401 Client Error: Unauthorized for url: {host}"] = (
                "Your Paddle API key is invalid, expired, or belongs to the other environment (live vs sandbox). Please check the key and the selected environment, then reconnect."
            )
            errors[f"403 Client Error: Forbidden for url: {host}"] = (
                "Your Paddle API key does not have the required permissions. Please check your API key permissions in Paddle and try again."
            )
        return errors

    def should_retry_non_retryable_errors(self) -> bool:
        return False

    def validate_credentials(
        self, config: PaddleSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            if validate_paddle_credentials(config.paddle_api_key, schema_name, environment=config.environment):
                return True, None
            else:
                return False, "Invalid Paddle API key"
        except PaddlePermissionError as e:
            return False, f"Paddle API key lacks permissions: {e}"
        except Exception as e:
            return False, str(e)

    def get_schemas(
        self,
        config: PaddleSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(PADDLE_INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(PADDLE_INCREMENTAL_FIELDS.get(endpoint)),
                # Every endpoint has webhook events carrying its entity (see
                # RESOURCE_TO_PADDLE_EVENTS), and none is webhook-only — the list API backfills
                # first, then webhook deliveries take over.
                supports_webhooks=True,
                incremental_fields=PADDLE_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in PADDLE_ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PaddleResumeConfig]:
        return ResumableSourceManager[PaddleResumeConfig](inputs, PaddleResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(self, config: PaddleSourceConfig, webhook_url: str, team_id: int) -> WebhookCreationResult:
        return create_paddle_webhook(config.paddle_api_key, config.environment, webhook_url)

    def get_desired_webhook_events(
        self, config: PaddleSourceConfig, eligible_schema_names: list[str]
    ) -> list[str] | None:
        # Every known event, not just the selected tables — auto-heals destinations created
        # before RESOURCE_TO_PADDLE_EVENTS gained new entries.
        return list(PADDLE_WEBHOOK_EVENTS)

    def sync_webhook_events(
        self,
        config: PaddleSourceConfig,
        webhook_url: str,
        team_id: int,
        eligible_schema_names: list[str],
    ) -> WebhookSyncResult:
        desired_events = self.get_desired_webhook_events(config, eligible_schema_names) or []
        return update_paddle_webhook_events(config.paddle_api_key, config.environment, webhook_url, desired_events)

    def get_external_webhook_info(
        self, config: PaddleSourceConfig, webhook_url: str, team_id: int
    ) -> ExternalWebhookInfo:
        return get_paddle_external_webhook_info(config.paddle_api_key, config.environment, webhook_url)

    def delete_webhook(self, config: PaddleSourceConfig, webhook_url: str, team_id: int) -> WebhookDeletionResult:
        return delete_paddle_webhook(config.paddle_api_key, config.environment, webhook_url)

    def source_for_pipeline(
        self,
        config: PaddleSourceConfig,
        resumable_source_manager: ResumableSourceManager[PaddleResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        webhook_source_manager = self.get_webhook_source_manager(inputs)

        return paddle_source(
            api_key=config.paddle_api_key,
            endpoint=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            webhook_source_manager=webhook_source_manager,
            environment=config.environment,
        )
