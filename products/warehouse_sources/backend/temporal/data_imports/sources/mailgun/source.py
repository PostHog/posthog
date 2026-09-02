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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mailgun import (
    MailgunSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun import (
    MailgunResumeConfig,
    create_webhook as create_mailgun_webhook,
    delete_webhook as delete_mailgun_webhook,
    get_external_webhook_info as get_mailgun_webhook_info,
    mailgun_source,
    sync_webhook_events as sync_mailgun_webhook_events,
    validate_credentials as validate_mailgun_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SCHEMA_TO_WEBHOOK_RESOURCE,
    WEBHOOK_EVENTS_ENDPOINT,
    WEBHOOK_TYPES,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

API_SECURITY_URL = "https://app.mailgun.com/settings/api_security"


@SourceRegistry.register
class MailgunSource(
    ResumableSource[MailgunSourceConfig, MailgunResumeConfig],
    WebhookSource[MailgunSourceConfig],
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    # Mailgun versions each resource in its own URL path (no account or header version), so the
    # per-endpoint paths in settings.py already target the newest route Mailgun serves for each
    # resource — /v4 for the domains listing, /v3 everywhere v4 doesn't exist. The source-level
    # label is therefore a pin recorded on the source, not a request-layer branch: every supported
    # version resolves to the same requests. Defaulting to v4 only stamps new sources; pinned v3
    # rows are byte-for-byte unaffected.
    supported_versions = ("v3", "v4")
    default_version = "v4"
    api_docs_url = "https://documentation.mailgun.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MAILGUN

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.webhook_template import (  # noqa: PLC0415
            template,
        )

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return SCHEMA_TO_WEBHOOK_RESOURCE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.mailgun.net": "Mailgun authentication failed. Please check your private API key.",
            "401 Client Error: Unauthorized for url: https://api.eu.mailgun.net": "Mailgun authentication failed. Please check your private API key and that the EU region is correct for your account.",
            "403 Client Error: Forbidden for url: https://api.mailgun.net": "Mailgun denied access. Please check that your API key has the required permissions.",
            "403 Client Error: Forbidden for url: https://api.eu.mailgun.net": "Mailgun denied access. Please check that your API key has the required permissions.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MAILGUN,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Mailgun",
            caption=f"""Enter your Mailgun private API key to pull your Mailgun data into the PostHog Data warehouse.

You can find your private API key in the [Mailgun dashboard]({API_SECURITY_URL}) under **Settings → API security**. Pick the region that matches where your Mailgun account is hosted.

Note: Mailgun only retains events for a limited period (1 day on free plans, up to 30 days on paid plans), so the initial events sync is bounded by your plan's retention.""",
            iconPath="/static/services/mailgun.png",
            docsUrl="https://posthog.com/docs/cdp/sources/mailgun",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Private API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.mailgun.net)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api.eu.mailgun.net)", value="eu"),
                        ],
                    ),
                ],
            ),
            webhookSetupCaption=(
                "PostHog registers a webhook on every sending domain of your account, for every "
                "Mailgun event type, using the API key above. Webhook events land in the "
                f"`{WEBHOOK_EVENTS_ENDPOINT}` table, which keeps history past the 1 to 30 days "
                "Mailgun retains events for.\n\n"
                "Mailgun doesn't return the signing key over the API, so copy it from "
                f"[Settings > API security]({API_SECURITY_URL}) (**HTTP webhook signing key**) into the "
                "field below. Deliveries are rejected until it's set.\n\n"
                "**Manual setup** (only needed if automatic registration failed):\n\n"
                "1. Go to **Send > Sending > Webhooks** in your Mailgun dashboard and pick a domain\n"
                "2. Add the URL shown below for each event type you want to sync\n"
                "3. Repeat for every sending domain you want covered"
            ),
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_secret",
                        label="HTTP webhook signing key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        caption=(
                            f"From [Settings > API security]({API_SECURITY_URL}). PostHog uses it to verify "
                            "the HMAC-SHA256 signature on every delivery."
                        ),
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MailgunSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=endpoint in INCREMENTAL_FIELDS,
                supports_append=endpoint in INCREMENTAL_FIELDS,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        # The pushed event stream has no list endpoint of its own to poll, so append and
        # full-refresh don't apply to it.
        schemas.append(
            SourceSchema(
                name=WEBHOOK_EVENTS_ENDPOINT,
                supports_incremental=False,
                supports_append=False,
                supports_webhooks=True,
                webhook_only=True,
                incremental_fields=[],
            )
        )

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: MailgunSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_mailgun_credentials(config.api_key, config.region):
            return True, None

        return False, "Invalid Mailgun API key or region"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MailgunResumeConfig]:
        return ResumableSourceManager[MailgunResumeConfig](inputs, MailgunResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(
        self, config: MailgunSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookCreationResult:
        return create_mailgun_webhook(config.api_key, config.region, webhook_url)

    def get_desired_webhook_events(
        self, config: MailgunSourceConfig, eligible_schema_names: list[str]
    ) -> list[str] | None:
        if WEBHOOK_EVENTS_ENDPOINT not in eligible_schema_names:
            return None
        return sorted(WEBHOOK_TYPES)

    def sync_webhook_events(
        self,
        config: MailgunSourceConfig,
        webhook_url: str,
        team_id: int,
        eligible_schema_names: list[str],
        api_version: str | None = None,
    ) -> WebhookSyncResult:
        if WEBHOOK_EVENTS_ENDPOINT not in eligible_schema_names:
            return WebhookSyncResult(success=True)
        return sync_mailgun_webhook_events(config.api_key, config.region, webhook_url)

    def get_external_webhook_info(
        self, config: MailgunSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> ExternalWebhookInfo | None:
        return get_mailgun_webhook_info(config.api_key, config.region, webhook_url)

    def delete_webhook(
        self, config: MailgunSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookDeletionResult:
        return delete_mailgun_webhook(config.api_key, config.region, webhook_url)

    def source_for_pipeline(
        self,
        config: MailgunSourceConfig,
        resumable_source_manager: ResumableSourceManager[MailgunResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return mailgun_source(
            api_key=config.api_key,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            webhook_source_manager=self.get_webhook_source_manager(inputs),
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
