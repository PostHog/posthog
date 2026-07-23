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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.yousign import (
    YouSignSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.yousign.settings import (
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    RESOURCE_TO_WEBHOOK_OBJECT_TYPE,
    YOUSIGN_ENDPOINTS,
    all_webhook_events,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.yousign.yousign import (
    YousignResumeConfig,
    create_webhook as create_yousign_webhook,
    delete_webhook as delete_yousign_webhook,
    get_external_webhook_info as get_yousign_webhook_info,
    update_webhook_events as update_yousign_webhook_events,
    validate_credentials as validate_yousign_credentials,
    yousign_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Webhook management calls run in the API request path where no job logger exists.
logger = structlog.get_logger(__name__)


@SourceRegistry.register
class YouSignSource(
    ResumableSource[YouSignSourceConfig, YousignResumeConfig],
    WebhookSource[YouSignSourceConfig],
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://developers.yousign.com/changelog"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.YOUSIGN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.YOU_SIGN,
            category=DataWarehouseSourceCategory.SALES,
            label="Yousign",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync signature requests, signers, documents, contacts, and more from Yousign into the PostHog Data warehouse.

Create an API key in the Yousign app under **Integrations → API keys**. Keys are environment-scoped, so pick the environment that matches your key — a sandbox key cannot access production data. A read-only, organization-scoped key is enough for syncing; managing webhooks automatically additionally requires a full-access key.""",
            iconPath="/static/services/yousign.png",
            docsUrl="https://posthog.com/docs/cdp/sources/yousign",
            keywords=["esignature", "e-signature", "electronic signature", "youtrust"],
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
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="production",
                        options=[
                            SourceFieldSelectConfigOption(label="Production", value="production"),
                            SourceFieldSelectConfigOption(label="Sandbox", value="sandbox"),
                        ],
                    ),
                ],
            ),
            webhookSetupCaption="""To set up the webhook manually:

1. In the Yousign app, go to **Integrations → Webhooks** and create a subscription
2. Paste the webhook URL shown below as the endpoint
3. Subscribe to the signature request lifecycle events (`signature_request.activated`, `signature_request.done`, `signature_request.expired`, and the other `signature_request.*` events)
4. Copy the subscription's **secret key** and paste it into the signing secret field below

If automatic creation failed, note that webhook management requires a full-access API key, and sandbox-scoped keys can only manage sandbox subscriptions.""",
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_secret",
                        label="Signing secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.yousign.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.yousign.webhook_template import (  # noqa: PLC0415
            template,
        )

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return RESOURCE_TO_WEBHOOK_OBJECT_TYPE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": (
                "Yousign rejected your API key. Check the key is correct, has not been revoked, and "
                "matches the selected environment (sandbox keys cannot access production), then reconnect."
            ),
            "403 Client Error": (
                "Your Yousign API key does not have permission to read this data. Check the key's "
                "scope and permissions in Yousign, then reconnect."
            ),
        }

    def get_schemas(
        self,
        config: YouSignSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Rows arrive newest-first with no sort control, so signature_requests is merge-only —
        # append mode needs a verified ordering guarantee the API doesn't give.
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            merge_only=("signature_requests",),
            supports_webhooks=("signature_requests",),
            descriptions=ENDPOINT_DESCRIPTIONS,
        )

    def validate_credentials(
        self,
        config: YouSignSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_yousign_credentials(config.api_key, config.environment, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[YousignResumeConfig]:
        return ResumableSourceManager[YousignResumeConfig](inputs, YousignResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(
        self, config: YouSignSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookCreationResult:
        return create_yousign_webhook(config.api_key, config.environment, webhook_url, logger)

    def get_desired_webhook_events(
        self, config: YouSignSourceConfig, eligible_schema_names: list[str]
    ) -> list[str] | None:
        # Every mappable event, not just the selected tables — auto-heals webhooks created before
        # WEBHOOK_EVENTS gained new entries.
        return all_webhook_events()

    def sync_webhook_events(
        self,
        config: YouSignSourceConfig,
        webhook_url: str,
        team_id: int,
        eligible_schema_names: list[str],
        api_version: str | None = None,
    ) -> WebhookSyncResult:
        desired_events = self.get_desired_webhook_events(config, eligible_schema_names) or []
        return update_yousign_webhook_events(config.api_key, config.environment, webhook_url, desired_events, logger)

    def get_external_webhook_info(
        self, config: YouSignSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> ExternalWebhookInfo:
        return get_yousign_webhook_info(config.api_key, config.environment, webhook_url)

    def delete_webhook(
        self, config: YouSignSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookDeletionResult:
        return delete_yousign_webhook(config.api_key, config.environment, webhook_url, logger)

    def source_for_pipeline(
        self,
        config: YouSignSourceConfig,
        resumable_source_manager: ResumableSourceManager[YousignResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in YOUSIGN_ENDPOINTS:
            raise ValueError(f"Unknown Yousign schema '{inputs.schema_name}'")

        return yousign_source(
            api_key=config.api_key,
            environment=config.environment,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            webhook_source_manager=self.get_webhook_source_manager(inputs),
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
