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

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zapsign import (
    ZapSignSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zapsign import zapsign as api_client
from products.warehouse_sources.backend.temporal.data_imports.sources.zapsign.settings import (
    DOCUMENTS_RESOURCE,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zapsign.zapsign import ZapSignResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC


@SourceRegistry.register
class ZapSignSource(
    ResumableSource[ZapSignSourceConfig, ZapSignResumeConfig],
    WebhookSource[ZapSignSourceConfig],
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.zapsign.com.br"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZAPSIGN

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # ZapSign answers 403 (not 401) for a missing/invalid API token.
        return {
            "403 Client Error: Forbidden": (
                "ZapSign rejected the API token. Copy a valid token from "
                "Settings > Integrations > ZapSign API and reconnect."
            ),
            "401 Client Error: Unauthorized": (
                "ZapSign rejected the API token. Copy a valid token from "
                "Settings > Integrations > ZapSign API and reconnect."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.zapsign.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.zapsign.webhook_template import template

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        # Every ZapSign document event routes to the single documents table, so the mapping is
        # keyed by the wildcard the Hog template looks up.
        return {DOCUMENTS_RESOURCE: "*"}

    def get_schemas(
        self,
        config: ZapSignSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Documents are merge-only: the created_from filter re-fetches the watermark's whole day,
        # so append mode would write duplicate rows.
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            merge_only=(DOCUMENTS_RESOURCE,),
            supports_webhooks=(DOCUMENTS_RESOURCE,),
        )

    def validate_credentials(
        self,
        config: ZapSignSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return api_client.validate_credentials(config.api_token, config.environment)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ZapSignResumeConfig]:
        return ResumableSourceManager[ZapSignResumeConfig](inputs, ZapSignResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(
        self, config: ZapSignSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookCreationResult:
        return api_client.create_webhook(config.api_token, config.environment, webhook_url)

    def delete_webhook(
        self, config: ZapSignSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookDeletionResult:
        return api_client.delete_webhook()

    def source_for_pipeline(
        self,
        config: ZapSignSourceConfig,
        resumable_source_manager: ResumableSourceManager[ZapSignResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return api_client.zapsign_source(
            api_token=config.api_token,
            environment=config.environment,
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

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZAP_SIGN,
            category=DataWarehouseSourceCategory.SALES,
            label="ZapSign",
            caption=(
                "Connect your ZapSign account using an API token to sync documents, signers, and "
                "templates. Find the token in ZapSign under **Settings** > **Integrations** > "
                "**ZapSign API**."
            ),
            keywords=["e-signature", "esignature", "digital signature"],
            iconPath="/static/services/zapsign.png",
            docsUrl="https://posthog.com/docs/cdp/sources/zapsign",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
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
                            SourceFieldSelectConfigOption(label="Production (api.zapsign.com.br)", value="production"),
                            SourceFieldSelectConfigOption(
                                label="Sandbox (sandbox.api.zapsign.com.br)", value="sandbox"
                            ),
                        ],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
            webhookSetupCaption=(
                "PostHog tries to register a webhook in ZapSign using your API token, subscribed "
                "to all document events (created, signed, refused, deleted). The webhook "
                "authenticates itself with an **Authorization** header PostHog generates and "
                "verifies on every delivery.\n\n"
                "**Manual setup** (only needed if auto-registration failed):\n\n"
                "1. In ZapSign, go to **Settings** > **Integrations** > **ZapSign API** > **Webhooks**\n"
                "2. Paste the webhook URL shown below\n"
                "3. Add an **Authorization** header with a secret value you generate — paste the "
                "same value into the field below so PostHog can verify deliveries\n"
                "4. Subscribe to all document events\n\n"
                "ZapSign has no API to look up webhooks later, so if you disconnect this source, "
                "remove the webhook in ZapSign manually."
            ),
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="authorization_header",
                        label="Authorization header value",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Bearer my-secret",
                        caption=(
                            "The exact value ZapSign will send in the Authorization header. "
                            "Must match what's configured on the ZapSign webhook."
                        ),
                        secret=True,
                    ),
                ],
            ),
        )
