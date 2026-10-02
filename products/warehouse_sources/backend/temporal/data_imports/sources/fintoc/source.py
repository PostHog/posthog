from typing import TYPE_CHECKING, cast

from asgiref.sync import async_to_sync

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
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
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.fintoc.fintoc import (
    FintocAPI,
    FintocResumeState,
    parse_link_tokens,
    webhook_table,
    webhook_template,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fintoc.settings import (
    API_VERSION,
    AUTH_ERROR,
    ENDPOINTS,
    LINK_TOKEN_ERROR,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fintoc import FintocSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC


@SourceRegistry.register
class FintocSource(ResumableSource[FintocSourceConfig, FintocResumeState], WebhookSource[FintocSourceConfig]):
    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://docs.fintoc.com/changelog"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FINTOC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Fintoc",
            iconPath="/static/services/fintoc.png",
            docsUrl="https://posthog.com/docs/cdp/sources/fintoc",
            keywords=["payments", "open banking", "fintech", "latam"],
            caption="Enter your Fintoc secret API key. Test keys import test data; live keys import live data. "
            "Accounts and movements need link tokens saved when exchanging links. "
            "Full refresh includes all available records. Optional webhook sync imports only event-delivered changes after the initial backfill.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        placeholder="sk_live_...",
                        label="Secret API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="link_tokens",
                        placeholder="",
                        label="Link tokens (comma-separated)",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        secret=True,
                    ),
                ],
            ),
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_secret",
                        placeholder="",
                        label="Signing secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                    )
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": PERMISSION_ERROR,
            "invalid_api_key": AUTH_ERROR,
            "invalid_link_token": AUTH_ERROR,
            LINK_TOKEN_ERROR: LINK_TOKEN_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.fintoc.canonical_descriptions import (  # noqa: PLC0415 - loads documentation only when requested
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def validate_credentials(
        self,
        config: FintocSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.api_key or not config.api_key.isascii() or any(char.isspace() for char in config.api_key):
            return False, "Enter a Fintoc secret API key without spaces or unsupported characters."
        return FintocAPI(config.api_key, self.resolve_api_version(api_version)).validate_credentials(
            schema_name, parse_link_tokens(config.link_tokens)
        )

    def get_schemas(
        self,
        config: FintocSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=name,
                supports_incremental=False,
                supports_append=False,
                supports_webhooks=bool(endpoint.webhook_events),
                should_sync_default=not endpoint.requires_link_token or bool(parse_link_tokens(config.link_tokens)),
            )
            for name, endpoint in ENDPOINTS.items()
            if names is None or name in names
        ]

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FintocResumeState]:
        return ResumableSourceManager(inputs, FintocResumeState)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    @property
    def webhook_template(self) -> "HogFunctionTemplateDC":
        return webhook_template()

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return {name: endpoint.webhook_object for name, endpoint in ENDPOINTS.items() if endpoint.webhook_object}

    def create_webhook(
        self,
        config: FintocSourceConfig,
        webhook_url: str,
        team_id: int,
        api_version: str | None = None,
    ) -> WebhookCreationResult:
        return FintocAPI(config.api_key, self.resolve_api_version(api_version)).create_webhook(webhook_url)

    def delete_webhook(
        self,
        config: FintocSourceConfig,
        webhook_url: str,
        team_id: int,
        api_version: str | None = None,
    ) -> WebhookDeletionResult:
        return FintocAPI(config.api_key, self.resolve_api_version(api_version)).delete_webhook(webhook_url)

    def get_external_webhook_info(
        self,
        config: FintocSourceConfig,
        webhook_url: str,
        team_id: int,
        api_version: str | None = None,
    ) -> ExternalWebhookInfo:
        return FintocAPI(config.api_key, self.resolve_api_version(api_version)).webhook_info(webhook_url)

    def source_for_pipeline(
        self,
        config: FintocSourceConfig,
        resumable_source_manager: ResumableSourceManager[FintocResumeState],
        inputs: SourceInputs,
    ) -> SourceResponse:
        response = FintocAPI(config.api_key, self.resolve_api_version(inputs.api_version)).source(
            inputs.schema_name,
            parse_link_tokens(config.link_tokens),
            inputs,
            resumable_source_manager,
        )
        if ENDPOINTS[inputs.schema_name].webhook_events:
            manager = self.get_webhook_source_manager(inputs)
            if async_to_sync(manager.webhook_enabled)():
                response.items = lambda: manager.get_items(table_transformer=webhook_table)
                response.supports_resume = False
        return response
