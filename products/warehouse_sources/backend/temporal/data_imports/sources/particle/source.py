from collections.abc import AsyncIterable, Iterable
from typing import TYPE_CHECKING, Any, Optional, cast

from asgiref.sync import async_to_sync

from products.warehouse_sources.backend.facade.codebase_detection import detect
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
    SimpleSource,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.particle import (
    ParticleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.particle.particle import (
    _webhook_table_transformer,
    create_webhook as create_particle_webhook,
    delete_webhook as delete_particle_webhook,
    get_external_webhook_info as get_particle_webhook_info,
    particle_source,
    probe_devices,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.particle.settings import (
    DEVICES_SCHEMA_NAME,
    ENDPOINTS,
    EVENTS_SCHEMA_NAME,
    WEBHOOK_RESOURCE_MAP,
    WEBHOOK_SCHEMA_NAMES,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from products.cdp.backend.templates.hog_function_template import HogFunctionTemplateDC


@SourceRegistry.register
class ParticleSource(
    SimpleSource[ParticleSourceConfig],
    WebhookSource[ParticleSourceConfig],
):
    codebase_detection = detect(
        env=("^PARTICLE_",),
        npm=("particle-api-js", "particle-cli"),
    )

    api_docs_url = "https://docs.particle.io/reference/cloud-apis/api/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PARTICLE

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.particle.webhook_template import (  # noqa: PLC0415
            template,
        )

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return dict(WEBHOOK_RESOURCE_MAP)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PARTICLE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Particle",
            keywords=["iot", "particle.io"],
            releaseStatus=ReleaseStatus.ALPHA,
            featureFlag="dwh-particle",
            caption="""Connect your [Particle](https://www.particle.io) devices. PostHog creates the Particle webhooks for you, and every `Particle.publish()` that matches your event name prefixes arrives as a PostHog event on that device, ready for insights, dashboards and alerts.

For **product devices**, use an **API user** token. In the Particle console, open your product → **Team** → **Add API user**, and give it these scopes:
- `devices:list` to sync your device list
- `integrations:list`, `integrations:create` and `integrations:remove` so PostHog can manage its webhooks

For **sandbox devices**, Particle has no API users, so use a personal access token for your account (`particle token create --never-expires` in the Particle CLI) and leave **Product ID** empty.
""",
            iconPath="/static/services/particle.png",
            docsUrl="https://posthog.com/docs/cdp/sources/particle",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Particle API user token",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="product_id",
                        label="Product ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="12345 (leave empty for sandbox devices)",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="event_prefixes",
                        label="Event name prefixes",
                        caption="Comma-separated. Particle matches event names by prefix, so `env/` receives `env/temp` and `env/humidity`.",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="env/, status",
                        secret=False,
                    ),
                ],
            ),
            webhookSetupCaption="""PostHog creates one Particle webhook per event name prefix, using your access token.

**Manual setup** (only needed if automatic setup failed):

1. In the Particle console, go to **Integrations** → **Add new integration** → **Webhook**
2. Set the event name to your prefix, the URL to the webhook URL shown below, and the request type to **POST**
3. Under **Advanced settings**, set a custom body of `{{{PARTICLE_EVENT_JSON}}}`, turn off the default data, and add these query parameters: `event` = `{{{PARTICLE_EVENT_NAME}}}`, `device_id` = `{{{PARTICLE_DEVICE_ID}}}`, `published_at` = `{{{PARTICLE_PUBLISHED_AT}}}`, `event_id` = `{{{PARTICLE_EVENT_ID}}}`, `product_id` = `{{{PRODUCT_ID}}}`, `firmware_version` = `{{{PRODUCT_VERSION}}}`
4. Add the headers `Content-Type: application/json` and `x-posthog-webhook-secret` with a value of your choosing, and paste the same value into the webhook secret field below""",
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

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.particle.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ParticleSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                supports_webhooks=endpoint in WEBHOOK_SCHEMA_NAMES,
                # Particle keeps no event history, so a full refresh would only delete the table.
                webhook_only=endpoint in WEBHOOK_SCHEMA_NAMES,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: ParticleSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        status = probe_devices(config)
        if status is not None and 200 <= status < 300:
            return True, None
        if status == 401:
            return False, "Invalid Particle access token. Please check the token and try again."
        if status == 403:
            return (
                False,
                "Your Particle access token can't list devices. Give the API user the `devices:list` scope and try again.",
            )
        if status == 404 and config.product_id:
            return (
                False,
                f"Particle product {config.product_id.strip()} was not found, or the token can't access it. Check the product ID.",
            )
        return False, "Couldn't reach Particle to verify your token. Please try again in a moment."

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.particle.io": (
                "Your Particle access token is invalid or expired. Please check the token and reconnect."
            ),
            "403 Client Error: Forbidden for url: https://api.particle.io": (
                "Your Particle access token can't list devices. Give the API user the `devices:list` scope and reconnect."
            ),
        }

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(
        self, config: ParticleSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookCreationResult:
        return create_particle_webhook(config, webhook_url)

    def get_external_webhook_info(
        self, config: ParticleSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> ExternalWebhookInfo:
        return get_particle_webhook_info(config, webhook_url)

    def delete_webhook(
        self, config: ParticleSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookDeletionResult:
        return delete_particle_webhook(config, webhook_url)

    def source_for_pipeline(self, config: ParticleSourceConfig, inputs: SourceInputs) -> SourceResponse:
        if inputs.schema_name == DEVICES_SCHEMA_NAME:
            return particle_source(config, inputs.team_id, inputs.job_id)
        if inputs.schema_name != EVENTS_SCHEMA_NAME:
            raise ValueError(f"Unknown Particle table: {inputs.schema_name}")

        webhook_source_manager = self.get_webhook_source_manager(inputs)
        webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)(webhook_only=True)

        def items() -> Iterable[Any] | AsyncIterable[Any]:
            if webhook_enabled:
                return webhook_source_manager.get_items(table_transformer=_webhook_table_transformer)
            return iter([])

        return SourceResponse(
            items=items,
            primary_keys=["event_id"],
            name=EVENTS_SCHEMA_NAME,
            webhook_only=True,
        )
