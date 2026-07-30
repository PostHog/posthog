from typing import TYPE_CHECKING, Optional, cast

import structlog

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.instantly import (
    InstantlySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instantly.instantly import (
    InstantlyResumeConfig,
    create_webhook as create_instantly_webhook,
    delete_webhook as delete_instantly_webhook,
    get_endpoint_permissions as get_instantly_endpoint_permissions,
    get_external_webhook_info as get_instantly_webhook_info,
    instantly_source,
    validate_credentials as validate_instantly_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instantly.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    INSTANTLY_ENDPOINTS,
    WEBHOOK_EVENTS_ENDPOINT,
    WEBHOOK_ROUTING_KEY,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Webhook management calls run in the API request path where no job logger exists.
logger = structlog.get_logger(__name__)


@SourceRegistry.register
class InstantlySource(
    ResumableSource[InstantlySourceConfig, InstantlyResumeConfig],
    WebhookSource[InstantlySourceConfig],
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developer.instantly.ai/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INSTANTLY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INSTANTLY,
            category=DataWarehouseSourceCategory.SALES,
            label="Instantly",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync campaigns, leads, emails, sending accounts, and analytics from Instantly into the PostHog Data warehouse.

Create an API key under **Settings → Integrations → API keys** in Instantly. The API requires the Growth plan or above.

API keys are scope-gated: the key needs a read scope for every table you sync (`all:read` covers everything; narrower keys like `campaigns:read`, `leads:read`, `emails:read`, or `accounts:read` work for their own tables). The optional webhook event stream additionally needs `webhooks:all` and the Hypergrowth plan or above.""",
            iconPath="/static/services/instantly.png",
            docsUrl="https://posthog.com/docs/cdp/sources/instantly",
            keywords=["cold email", "email outreach", "sales engagement", "instantly.ai"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            webhookSetupCaption="""To set up the webhook manually:

1. In Instantly, go to **Settings → Integrations → Webhooks** (or use the API) and create a webhook
2. Set the target URL to the webhook URL shown below and the event type to **All events**
3. Add a custom header named `x-posthog-webhook-secret` with a value of your choosing, and paste the same value into the webhook secret field below

Instantly webhooks require the Hypergrowth plan or above, and automatic creation needs an API key with the `webhooks:all` (or `all:all`) scope.""",
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_secret",
                        label="Webhook secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.instantly.ai": "Instantly rejected your API key. Check the key is correct and has not been revoked, then reconnect.",
            "402 Client Error: Payment Required for url: https://api.instantly.ai": "Your Instantly workspace does not have an active plan with API access (the API requires the Growth plan or above).",
            "403 Client Error: Forbidden for url: https://api.instantly.ai": "Your Instantly API key does not have the scope required for this table. Grant the matching read scope (or use an `all:read` key), then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.instantly.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.instantly.webhook_template import (  # noqa: PLC0415
            template,
        )

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return {WEBHOOK_EVENTS_ENDPOINT: WEBHOOK_ROUTING_KEY}

    def get_schemas(
        self,
        config: InstantlySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names=None,
            descriptions={
                name: config_.description for name, config_ in INSTANTLY_ENDPOINTS.items() if config_.description
            },
        )
        schemas.append(
            SourceSchema(
                name=WEBHOOK_EVENTS_ENDPOINT,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                supports_webhooks=True,
                webhook_only=True,
                description=(
                    "Raw Instantly webhook event stream (sends, opens, replies, bounces, lead status "
                    "changes). Requires the webhook to be enabled — Hypergrowth plan or above."
                ),
            )
        )
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: InstantlySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_instantly_credentials(config.api_key, schema_name)

    def get_endpoint_permissions(
        self, config: InstantlySourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        return get_instantly_endpoint_permissions(config.api_key, endpoints)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[InstantlyResumeConfig]:
        return ResumableSourceManager[InstantlyResumeConfig](inputs, InstantlyResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(
        self, config: InstantlySourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookCreationResult:
        return create_instantly_webhook(config.api_key, webhook_url, logger)

    def get_external_webhook_info(
        self, config: InstantlySourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> ExternalWebhookInfo:
        return get_instantly_webhook_info(config.api_key, webhook_url, logger)

    def delete_webhook(
        self, config: InstantlySourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookDeletionResult:
        return delete_instantly_webhook(config.api_key, webhook_url, logger)

    def source_for_pipeline(
        self,
        config: InstantlySourceConfig,
        resumable_source_manager: ResumableSourceManager[InstantlyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name != WEBHOOK_EVENTS_ENDPOINT and inputs.schema_name not in INSTANTLY_ENDPOINTS:
            raise ValueError(f"Unknown Instantly schema '{inputs.schema_name}'")

        return instantly_source(
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
