from typing import cast

from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.browse_ai.browse_ai import (
    BrowseAIResumeConfig,
    BrowseAIWebhooks,
    browse_ai_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.browse_ai.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PERMISSION_ERROR,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.browseai import (
    BrowseAISourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BrowseAISource(ResumableSource[BrowseAISourceConfig, BrowseAIResumeConfig], WebhookSource[BrowseAISourceConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://docs.browse.ai/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BROWSEAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BROWSEAI,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Browse AI",
            iconPath="/static/services/browse_ai.png",
            docsUrl="https://posthog.com/docs/cdp/sources/browse-ai",
            keywords=["web scraping", "data extraction", "monitoring", "automation"],
            caption="Enter an API key from your [Browse AI dashboard](https://dashboard.browse.ai/api). "
            "Task results remain nested. Results above 100 KB may contain temporary download links instead of captured data.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        placeholder="",
                        required=True,
                        secret=True,
                    )
                ],
            ),
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="webhook_token",
                        label="Webhook token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        placeholder="",
                        required=True,
                        secret=True,
                    )
                ],
            ),
            webhookSetupCaption="Connect webhooks again after adding robots to Browse AI. Each connection registers task completion events on your current robots.",
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_schemas(
        self,
        config: BrowseAISourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, supports_webhooks={"tasks"})

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.browse_ai.canonical_descriptions import (  # noqa: PLC0415 - load descriptions only when enrichment needs them
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def validate_credentials(
        self,
        config: BrowseAISourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, f"Unknown Browse AI schema: {schema_name}"
        return validate_credentials(config.api_key)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.browse.ai": AUTH_ERROR,
            "403 Client Error: Forbidden for url: https://api.browse.ai": PERMISSION_ERROR,
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BrowseAIResumeConfig]:
        return ResumableSourceManager(inputs, BrowseAIResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def source_for_pipeline(
        self,
        config: BrowseAISourceConfig,
        resumable_source_manager: ResumableSourceManager[BrowseAIResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return browse_ai_source(
            config.api_key, inputs, resumable_source_manager, self.get_webhook_source_manager(inputs)
        )

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return {"tasks": "task"}

    def create_webhook(
        self,
        config: BrowseAISourceConfig,
        webhook_url: str,
        team_id: int,
        api_version: str | None = None,
    ) -> WebhookCreationResult:
        return BrowseAIWebhooks(config.api_key).create(webhook_url)

    def delete_webhook(
        self,
        config: BrowseAISourceConfig,
        webhook_url: str,
        team_id: int,
        api_version: str | None = None,
    ) -> WebhookDeletionResult:
        return BrowseAIWebhooks(config.api_key).delete(webhook_url)

    def get_external_webhook_info(
        self,
        config: BrowseAISourceConfig,
        webhook_url: str,
        team_id: int,
        api_version: str | None = None,
    ) -> ExternalWebhookInfo:
        return BrowseAIWebhooks(config.api_key).info(webhook_url)

    @property
    def webhook_template(self) -> HogFunctionTemplateDC:
        return HogFunctionTemplateDC(
            status="alpha",
            free=False,
            type="warehouse_source_webhook",
            id="template-warehouse-source-browse-ai",
            name="Browse AI warehouse source webhook",
            description="Receive Browse AI task completion events for data warehouse ingestion",
            icon_url="/static/services/browse_ai.png",
            category=["Data warehouse"],
            code_language="hog",
            code="""
if (request.method != 'POST') {
    return {'httpResponse': {'status': 405, 'body': 'Method not allowed'}}
}
if (empty(inputs.webhook_token) or request.query.token != inputs.webhook_token) {
    return {'httpResponse': {'status': 401, 'body': 'Invalid webhook token'}}
}
if (request.body.event not in ['task.finishedSuccessfully', 'task.finishedWithError', 'task.capturedDataChanged']) {
    return {'httpResponse': {'status': 200, 'body': 'Event ignored'}}
}
if (empty(request.body.task.id) or empty(request.body.task.robotId)) {
    return {'httpResponse': {'status': 400, 'body': 'Missing task identifiers'}}
}
let schemaId := inputs.schema_mapping?.task
if (not empty(schemaId)) {
    produceToWarehouseWebhooks({'task': request.body.task}, schemaId)
}
""",
            inputs_schema=[
                {"type": "string", "key": "webhook_token", "label": "Webhook token", "required": True, "secret": True},
                {"type": "json", "key": "schema_mapping", "label": "Schema mapping", "required": True, "hidden": True},
                {"type": "string", "key": "source_id", "label": "Source ID", "required": True, "hidden": True},
            ],
        )
