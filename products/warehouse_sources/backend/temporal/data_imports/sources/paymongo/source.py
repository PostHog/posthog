from typing import TYPE_CHECKING, cast

from requests.exceptions import HTTPError

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.paymongo import (
    PaymongoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paymongo.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paymongo.paymongo import (
    PaymongoClient,
    PaymongoResumeConfig,
    paymongo_source,
    webhook_template,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paymongo.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC


def webhook_error(error: HTTPError) -> str:
    status = error.response.status_code if error.response is not None else "unknown"
    return (
        f"PayMongo could not update the webhook (HTTP {status}). Check your API key and webhook settings, then retry."
    )


@SourceRegistry.register
class PaymongoSource(ResumableSource[PaymongoSourceConfig, PaymongoResumeConfig], WebhookSource[PaymongoSourceConfig]):
    lists_tables_without_credentials = True
    api_docs_url = "https://docs.paymongo.com/reference/list-all-payments"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PAYMONGO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PAYMONGO,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="PayMongo",
            iconPath="/static/services/paymongo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/paymongo",
            caption="Import payments, refunds, payment links, payouts, and webhook settings from PayMongo.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Secret API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="",
                        caption="Copy your secret API key from your [PayMongo dashboard](https://dashboard.paymongo.com). Test keys import test data; live keys import live data.",
                    )
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
            webhookSetupCaption="PostHog registers payment webhooks automatically. For manual setup, add the URL below in PayMongo, select payment.paid, payment.failed, payment.refunded, and payment.refund.updated, then copy the signing secret below. Disconnecting disables the webhook in PayMongo.",
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_secret",
                        label="Signing secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="",
                    )
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "PayMongo rejected your API key. Replace the invalid or expired key and reconnect.",
            "403 Client Error: Forbidden": "Your PayMongo API key cannot access this table. Check your account permissions.",
        }

    def get_schemas(
        self,
        config: PaymongoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, supports_webhooks=("payments",))

    def validate_credentials(
        self, config: PaymongoSourceConfig, team_id: int, schema_name: str | None = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        return PaymongoClient(config.api_key).validate_credentials(schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PaymongoResumeConfig]:
        return ResumableSourceManager(inputs, PaymongoResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    @property
    def webhook_template(self) -> "HogFunctionTemplateDC":
        return webhook_template()

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return {"payments": "payment"}

    def create_webhook(
        self, config: PaymongoSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookCreationResult:
        try:
            return PaymongoClient(config.api_key).create_webhook(webhook_url)
        except HTTPError as error:
            return WebhookCreationResult(success=False, error=webhook_error(error))

    def delete_webhook(
        self, config: PaymongoSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookDeletionResult:
        try:
            return PaymongoClient(config.api_key).delete_webhook(webhook_url)
        except HTTPError as error:
            return WebhookDeletionResult(success=False, error=webhook_error(error))

    def get_external_webhook_info(
        self, config: PaymongoSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> ExternalWebhookInfo:
        return PaymongoClient(config.api_key).get_external_webhook_info(webhook_url)

    def source_for_pipeline(
        self,
        config: PaymongoSourceConfig,
        resumable_source_manager: ResumableSourceManager[PaymongoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return paymongo_source(
            config.api_key, inputs, resumable_source_manager, self.get_webhook_source_manager(inputs)
        )
