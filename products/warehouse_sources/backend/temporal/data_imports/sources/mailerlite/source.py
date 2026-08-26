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
    VersionDeprecation,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mailerlite import (
    MailerLiteSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite import mailerlite as api_client
from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.mailerlite import (
    MailerLiteResumeConfig,
    mailerlite_source,
    validate_credentials as validate_mailerlite_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.settings import (
    DEFAULT_VERSION,
    ENDPOINTS,
    MAILERLITE_ENDPOINTS,
    MAILERLITE_V1,
    SCHEMA_TO_WEBHOOK_EVENTS,
    SUPPORTED_VERSIONS,
    WEBHOOK_RESOURCE_MAP,
    WEBHOOK_SCHEMA_NAMES,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC


@SourceRegistry.register
class MailerLiteSource(
    ResumableSource[MailerLiteSourceConfig, MailerLiteResumeConfig],
    WebhookSource[MailerLiteSourceConfig],
):
    api_docs_url = "https://developers.mailerlite.com"

    supported_versions = SUPPORTED_VERSIONS
    default_version = DEFAULT_VERSION

    # v1 sends no `X-Version` header, so connect.mailerlite.com serves whatever it treats as
    # "latest" — the drift the pin exists to stop; v2 pins the documented version date. The vendor
    # is deprecating v1 with no announced sunset date (`sunset_at=None`), so this is advisory: it
    # lights up the generic in-product banner. Existing v1 pins are left in place — the vendor still
    # serves them, and repinning would silently move a customer to a different wire — so the user
    # repins from the source config when ready.
    deprecated_versions = (VersionDeprecation(version=MAILERLITE_V1),)

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MAILERLITE

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.webhook_template import (
            template,
        )

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return WEBHOOK_RESOURCE_MAP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MAILER_LITE,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="MailerLite",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your MailerLite API key to pull your MailerLite data into the PostHog Data warehouse.

You can create an API key in your [MailerLite integrations settings](https://dashboard.mailerlite.com/integrations/api).""",
            iconPath="/static/services/mailerlite.png",
            docsUrl="https://posthog.com/docs/cdp/sources/mailerlite",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your MailerLite API key",
                        secret=True,
                    ),
                ],
            ),
            webhookSetupCaption="""PostHog registers a MailerLite webhook for your subscriber events using your API key. MailerLite generates the signing secret and returns it once, at creation, so PostHog stores it then and uses it to verify every delivery.

**Manual setup** (only needed if automatic registration failed):

MailerLite only manages webhooks through its API, so create one with a request like this, using the webhook URL shown below:

```
curl -X POST https://connect.mailerlite.com/api/webhooks \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"name": "PostHog Data warehouse", "url": "YOUR_WEBHOOK_URL", "events": ["subscriber.created", "subscriber.updated", "subscriber.unsubscribed", "subscriber.bounced", "subscriber.spam_reported", "subscriber.active", "subscriber.added_to_group", "subscriber.removed_from_group"]}'
```

Copy the `secret` from the response into the field below. MailerLite never returns it again, so if you lose it, delete the webhook and create a new one.""",
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
                            "The secret MailerLite returned when the webhook was created. PostHog "
                            "uses it to verify the Signature header on every delivery."
                        ),
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://connect.mailerlite.com": "Your MailerLite API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error: Forbidden for url: https://connect.mailerlite.com": "Your MailerLite API key does not have the required permissions. Please check the key and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MailerLiteSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # MailerLite exposes no server-side timestamp filter, so every endpoint is full-refresh only
        # (no incremental fields → build_endpoint_schemas marks each supports_incremental=False).
        return build_endpoint_schemas(ENDPOINTS, {}, names, supports_webhooks=WEBHOOK_SCHEMA_NAMES)

    def validate_credentials(
        self,
        config: MailerLiteSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        endpoint_config = MAILERLITE_ENDPOINTS.get(schema_name) if schema_name else None
        path = endpoint_config.path if endpoint_config else "/subscribers"
        if validate_mailerlite_credentials(config.api_key, path):
            return True, None

        return False, "Invalid MailerLite API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MailerLiteResumeConfig]:
        return ResumableSourceManager[MailerLiteResumeConfig](inputs, MailerLiteResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(
        self, config: MailerLiteSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookCreationResult:
        return api_client.create_webhook(config.api_key, webhook_url)

    def get_desired_webhook_events(
        self, config: MailerLiteSourceConfig, eligible_schema_names: list[str]
    ) -> list[str] | None:
        return sorted({event for name in eligible_schema_names for event in SCHEMA_TO_WEBHOOK_EVENTS.get(name, ())})

    def sync_webhook_events(
        self,
        config: MailerLiteSourceConfig,
        webhook_url: str,
        team_id: int,
        eligible_schema_names: list[str],
        api_version: str | None = None,
    ) -> WebhookSyncResult:
        desired_events = self.get_desired_webhook_events(config, eligible_schema_names) or []
        return api_client.sync_webhook_events(config.api_key, webhook_url, desired_events)

    def get_external_webhook_info(
        self, config: MailerLiteSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> ExternalWebhookInfo | None:
        return api_client.get_external_webhook_info(config.api_key, webhook_url)

    def delete_webhook(
        self, config: MailerLiteSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookDeletionResult:
        return api_client.delete_webhook(config.api_key, webhook_url)

    def source_for_pipeline(
        self,
        config: MailerLiteSourceConfig,
        resumable_source_manager: ResumableSourceManager[MailerLiteResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return mailerlite_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            webhook_source_manager=self.get_webhook_source_manager(inputs),
            api_version=self.resolve_api_version(inputs.api_version),
        )
