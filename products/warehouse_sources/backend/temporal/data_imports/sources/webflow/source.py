from typing import TYPE_CHECKING, Optional, cast

import structlog

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.webflow import (
    WebflowSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.settings import (
    COLLECTION_SCHEMA_PREFIX,
    SCHEMA_TO_WEBHOOK_EVENTS,
    STATIC_ENDPOINTS,
    WEBHOOK_RESOURCE_MAP,
    WEBHOOK_SCHEMA_NAMES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.webflow import (
    WebflowResumeConfig,
    create_webhook as create_webflow_webhook,
    delete_webhook as delete_webflow_webhook,
    get_external_webhook_info as get_webflow_webhook_info,
    list_collections,
    validate_credentials as validate_webflow_credentials,
    webflow_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

logger = structlog.get_logger(__name__)


@SourceRegistry.register
class WebflowSource(
    ResumableSource[WebflowSourceConfig, WebflowResumeConfig],
    WebhookSource[WebflowSourceConfig],
):
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developers.webflow.com"

    # Only the static endpoint catalog is credential-free; CMS-collection discovery (a network
    # call) is skipped when credentials are absent, so the public-docs path stays I/O-free.
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WEBFLOW

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Webflow API token is invalid or expired. Please generate a new token and reconnect.",
            "403 Client Error": "Your Webflow API token is missing a required scope. Grant the read scopes for the resources you want to sync and reconnect.",
            # Webflow returns 409 Conflict on the Products/Orders list endpoints when the
            # connected site does not have ecommerce enabled, and on other resources when
            # the site has unpublished changes. Both are deterministic state/config issues
            # that retrying can't resolve, so stop retrying and tell the user how to fix it.
            "409 Client Error: Conflict": "Webflow returned a 409 Conflict. For the Products and Orders tables this means the connected site does not have ecommerce enabled — enable ecommerce in Webflow or remove those tables from the sync. For other resources it can mean the site has unpublished changes; publish your Webflow site, then try again.",
            # Webflow returns 406 deterministically for a given site/token — every retry of the
            # same request fails identically, so it's a site-side rejection retrying can't fix
            # rather than a transient content-negotiation blip. Webflow doesn't document the
            # exact cause; it's commonly reported when the connected site's plan doesn't include
            # CMS API access. Match the stable status text, not the URL.
            "406 Client Error": "Webflow rejected this request with a 406 Not Acceptable error. This usually means the connected site isn't eligible for the requested resource — for example, CMS collections require a Webflow site plan with CMS access. Check your Webflow site's plan and settings, then try again.",
            # A CMS collection discovered when the table was set up can later be deleted or have its
            # slug renamed in Webflow, so at sync time the slug no longer resolves to a collection.
            # That's a deterministic upstream state change retrying can't fix. Match the stable
            # prefix, not the schema name and site id that follow it.
            "Webflow collection for schema": "A Webflow CMS collection PostHog was syncing no longer exists on your site. It was deleted or renamed in Webflow. Refresh this source's schemas to pick up your current collections, then remove the table for the collection that's gone.",
        }

    def get_schemas(
        self,
        config: WebflowSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Webflow has no verified server-side timestamp range filter on its list
        # endpoints (the createdOn/lastUpdated query params are exact-match, not
        # ranges), so every endpoint is full-refresh only for now.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                supports_webhooks=endpoint in WEBHOOK_SCHEMA_NAMES,
            )
            for endpoint in STATIC_ENDPOINTS
        ]

        # Each site exposes a different set of CMS collections, so discover them
        # dynamically and expose one schema per collection. Best-effort: if the
        # token can't list collections (missing scope, transient error) we still
        # return the static endpoints rather than failing the whole source.
        # Skip the network call entirely without credentials (e.g. the credential-free
        # public-docs catalog path), so an unauthenticated caller can't trigger it.
        if config.api_token and config.site_id:
            try:
                for collection in list_collections(config.api_token, config.site_id):
                    slug = collection.get("slug")
                    if not slug:
                        continue
                    schemas.append(
                        SourceSchema(
                            name=f"{COLLECTION_SCHEMA_PREFIX}{slug}",
                            supports_incremental=False,
                            supports_append=False,
                            incremental_fields=[],
                            label=collection.get("displayName"),
                        )
                    )
            except Exception as e:
                # Best-effort: a missing scope, transient network error, or schema-discovery
                # bug shouldn't fail the whole source. Log so the cause is debuggable.
                logger.debug("Webflow: failed to discover CMS collections, returning static endpoints only", exc_info=e)

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: WebflowSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_webflow_credentials(config.api_token, config.site_id, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WebflowResumeConfig]:
        return ResumableSourceManager[WebflowResumeConfig](inputs, WebflowResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.webhook_template import template

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return WEBHOOK_RESOURCE_MAP

    def create_webhook(
        self, config: WebflowSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookCreationResult:
        return create_webflow_webhook(config.api_token, config.site_id, webhook_url)

    def get_desired_webhook_events(
        self, config: WebflowSourceConfig, eligible_schema_names: list[str]
    ) -> list[str] | None:
        return sorted({event for name in eligible_schema_names for event in SCHEMA_TO_WEBHOOK_EVENTS.get(name, [])})

    # `sync_webhook_events` stays on the base no-op. Webflow issues a registration's signing
    # secret once, at creation, and reconciliation has no way to persist a new one — so a
    # webhook re-created here would deliver events we could never verify. There is nothing to
    # drift anyway: `create_webhook` registers every trigger the one eligible table needs, and
    # anything missing afterwards is surfaced to the user by `get_desired_webhook_events`.

    def get_external_webhook_info(
        self, config: WebflowSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> ExternalWebhookInfo | None:
        return get_webflow_webhook_info(config.api_token, config.site_id, webhook_url)

    def delete_webhook(
        self, config: WebflowSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookDeletionResult:
        return delete_webflow_webhook(config.api_token, config.site_id, webhook_url)

    def source_for_pipeline(
        self,
        config: WebflowSourceConfig,
        resumable_source_manager: ResumableSourceManager[WebflowResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return webflow_source(
            api_token=config.api_token,
            site_id=config.site_id,
            schema_name=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            webhook_source_manager=self.get_webhook_source_manager(inputs),
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WEBFLOW,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Webflow",
            caption="""Enter your Webflow v2 API token and Site ID to pull your Webflow site data into the PostHog Data warehouse.

Create a **Site API token** in Webflow under **Site settings → Apps & integrations → API access**, and copy the **Site ID** from the same page (or from your site's URL in the Designer).

Grant the read scopes for the resources you want to sync:
- `sites:read`
- `cms:read` (collections and collection items)
- `ecommerce:read` (products and orders)
- `pages:read`
- `users:read`
- `forms:read`
""",
            iconPath="/static/services/webflow.png",
            docsUrl="https://posthog.com/docs/cdp/sources/webflow",
            releaseStatus=ReleaseStatus.ALPHA,
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
                    SourceFieldInputConfig(
                        name="site_id",
                        label="Site ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
            webhookSetupCaption=(
                "PostHog registers a Webflow webhook for each order event using your API token, "
                "which needs the `sites:write` scope. Webflow returns a secret key for each "
                "registration, and PostHog uses those to verify deliveries.\n\n"
                "**Manual setup** (only needed if automatic registration failed):\n\n"
                "1. Send a POST request to Webflow's [Create Webhook]"
                "(https://developers.webflow.com/data/reference/webhooks/create) endpoint for "
                'your site, once with `"triggerType": "ecomm_new_order"` and once with '
                '`"triggerType": "ecomm_order_changed"`, using the webhook URL shown below\n'
                "2. Copy the `secretKey` from a response and paste it into the field below so "
                "PostHog can verify deliveries\n\n"
                "Webhooks created from Webflow's site settings are not signed, so PostHog cannot "
                "accept them. Create them through the API."
            ),
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
                            "The `secretKey` Webflow returned when the webhook was created. PostHog "
                            "uses it to verify the x-webflow-signature header on every delivery."
                        ),
                        secret=True,
                    ),
                ],
            ),
        )
