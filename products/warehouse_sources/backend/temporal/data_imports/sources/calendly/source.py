from typing import TYPE_CHECKING, Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.calendly import (
    CALENDLY_API_VERSION_V1,
    CALENDLY_API_VERSION_V2,
    SUPPORTED_API_VERSIONS,
    CalendlyResumeConfig,
    calendly_source,
    create_webhook as create_calendly_webhook,
    delete_webhook as delete_calendly_webhook,
    get_external_webhook_info as get_calendly_webhook_info,
    validate_credentials as validate_calendly_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.settings import (
    CALENDLY_WEBHOOK_EVENTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    WEBHOOK_RESOURCE_MAP,
    WEBHOOK_SCHEMA_NAMES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    FieldType,
    ResumableSource,
    VersionDeprecation,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.calendly import (
    CalendlySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC


@SourceRegistry.register
class CalendlySource(
    ResumableSource[CalendlySourceConfig, CalendlyResumeConfig],
    WebhookSource[CalendlySourceConfig],
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://developer.calendly.com/"

    supported_versions = SUPPORTED_API_VERSIONS
    default_version = CALENDLY_API_VERSION_V2
    # The "v1" label is this source's legacy default, not Calendly's retired v1 API — both labels
    # have always resolved to the same live host. So the vendor's 2025-08-27 v1 sunset is not a
    # sunset for these pins: nothing stops working, and `sunset_at` stays None. The label is
    # deprecated so the in-product banner nudges users onto v2 at their own pace.
    deprecated_versions = (VersionDeprecation(version=CALENDLY_API_VERSION_V1, sunset_at=None),)

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CALENDLY

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.webhook_template import template

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return WEBHOOK_RESOURCE_MAP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CALENDLY,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Calendly",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Calendly personal access token to pull your Calendly data into the PostHog Data warehouse.

You can create a personal access token in Calendly under **Integrations → API & Webhooks**. A personal access token requires a paid Calendly plan.""",
            iconPath="/static/services/calendly.png",
            docsUrl="https://posthog.com/docs/cdp/sources/calendly",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="personal_access_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            webhookSetupCaption="""PostHog registers an organization-wide webhook subscription with your personal access token, using a generated signing key to verify every delivery. Webhooks need a Calendly Standard plan or higher, and an organization-wide subscription needs an admin or owner token.

**Manual setup** (only needed if automatic registration failed):

Calendly has no webhook screen in its dashboard, so subscriptions are created through its API. Get your organization URI from `GET https://api.calendly.com/users/me`, pick a random signing key, then run:

```
curl -X POST https://api.calendly.com/webhook_subscriptions \\
  -H "Authorization: Bearer YOUR_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"url": "THE_WEBHOOK_URL_BELOW", "events": ["invitee.created", "invitee.canceled"], "organization": "YOUR_ORGANIZATION_URI", "scope": "organization", "signing_key": "YOUR_SIGNING_KEY"}'
```

Paste the same signing key into the field below so PostHog can verify deliveries.""",
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_secret",
                        label="Signing key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        caption=(
                            "The signing key set on the Calendly webhook subscription. PostHog uses it to "
                            "verify the Calendly-Webhook-Signature header on every delivery."
                        ),
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CalendlySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, supports_webhooks=WEBHOOK_SCHEMA_NAMES)

    def validate_credentials(
        self,
        config: CalendlySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_calendly_credentials(config.personal_access_token):
            return True, None

        return False, "Invalid Calendly personal access token"

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.calendly.com": "Your Calendly personal access token is invalid or expired. Please generate a new token and reconnect.",
            "403 Client Error: Forbidden for url: https://api.calendly.com": "Your Calendly personal access token does not have the required permissions. Please check the token and try again.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CalendlyResumeConfig]:
        return ResumableSourceManager[CalendlyResumeConfig](inputs, CalendlyResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(
        self, config: CalendlySourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookCreationResult:
        return create_calendly_webhook(config.personal_access_token, webhook_url, self.resolve_api_version(api_version))

    def get_desired_webhook_events(
        self, config: CalendlySourceConfig, eligible_schema_names: list[str]
    ) -> list[str] | None:
        # Fixed regardless of the selected schemas: both events feed the one webhook-capable table,
        # and Calendly subscriptions are immutable, so there is nothing to reconcile afterwards.
        return list(CALENDLY_WEBHOOK_EVENTS)

    def get_external_webhook_info(
        self, config: CalendlySourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> ExternalWebhookInfo | None:
        return get_calendly_webhook_info(
            config.personal_access_token, webhook_url, self.resolve_api_version(api_version)
        )

    def delete_webhook(
        self, config: CalendlySourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookDeletionResult:
        return delete_calendly_webhook(config.personal_access_token, webhook_url, self.resolve_api_version(api_version))

    def source_for_pipeline(
        self,
        config: CalendlySourceConfig,
        resumable_source_manager: ResumableSourceManager[CalendlyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return calendly_source(
            token=config.personal_access_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            webhook_source_manager=self.get_webhook_source_manager(inputs),
            api_version=self.resolve_api_version(inputs.api_version),
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
