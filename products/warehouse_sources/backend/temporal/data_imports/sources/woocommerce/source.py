from typing import TYPE_CHECKING, Optional, cast

from asgiref.sync import async_to_sync

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.woocommerce import (
    WooCommerceSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PARTITION_FIELDS,
    SCHEMA_TO_WEBHOOK_RESOURCE,
    WEBHOOK_SCHEMA_NAMES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.woocommerce import (
    WooCommerceResumeConfig,
    create_webhook as create_woocommerce_webhook,
    delete_webhook as delete_woocommerce_webhook,
    get_external_webhook_info as get_woocommerce_webhook_info,
    validate_credentials as validate_woocommerce_credentials,
    webhook_table_transformer,
    woocommerce_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

WEBHOOK_SETUP_CAPTION = (
    "PostHog registers a webhook on your store for each of the product, order, coupon and customer "
    "created and updated topics, using the API key above. The key needs **Read/Write** permission "
    "for this to work.\n\n"
    "**Manual setup** (only needed if automatic registration failed):\n\n"
    "1. Go to **WooCommerce > Settings > Advanced > Webhooks** in your store admin\n"
    "2. Add one webhook per topic you want, pointing its delivery URL at the URL shown below\n"
    "3. Give every one of them the same secret, and paste that secret into the field below so "
    "PostHog can verify deliveries"
)


@SourceRegistry.register
class WooCommerceSource(
    ResumableSource[WooCommerceSourceConfig, WooCommerceResumeConfig],
    WebhookSource[WooCommerceSourceConfig],
):
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://woocommerce.github.io/woocommerce-rest-api-docs/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WOOCOMMERCE

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.webhook_template import (  # noqa: PLC0415
            template,
        )

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        # WooCommerce identifies the object type in the `X-WC-Webhook-Resource` header rather than
        # the body, so deliveries are routed by resource and both of a resource's topics land on
        # the same table.
        return SCHEMA_TO_WEBHOOK_RESOURCE

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # WooCommerce's own auth and permission failures return 401 (e.g. a bad key or a key
        # without Read scope). A 403 on the REST API almost always comes from an upstream layer
        # — a WAF, CDN, or security plugin — blocking the request before it reaches WooCommerce,
        # so point users at that rather than blaming their key.
        return {
            "401 Client Error": (
                "WooCommerce rejected the request. Check your consumer key and secret are correct "
                "and have Read permission for this store."
            ),
            "403 Client Error": (
                "The request to your WooCommerce store was blocked before it reached WooCommerce, "
                "usually by a firewall, CDN, or security plugin. Allow requests to the store's REST "
                "API (/wp-json/wc/v3) and try again."
            ),
        }

    def get_schemas(
        self,
        config: WooCommerceSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, supports_webhooks=WEBHOOK_SCHEMA_NAMES)

    def validate_credentials(
        self,
        config: WooCommerceSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.store_url or not config.consumer_key or not config.consumer_secret:
            return False, "Missing WooCommerce credentials"

        status = validate_woocommerce_credentials(
            config.store_url, config.consumer_key, config.consumer_secret, team_id
        )

        if status == 200:
            return True, None

        # A 403 on the probe endpoint is almost always an upstream block (WAF/CDN/security
        # plugin), not the key itself, and can be endpoint-specific. Don't fail source creation
        # on it — let the source be created and surface any real block per-schema at sync time
        # via `get_non_retryable_errors`.
        if status == 403 and schema_name is None:
            return True, None

        if status == 403:
            return False, (
                "The request to your WooCommerce store was blocked before it reached WooCommerce, "
                "usually by a firewall, CDN, or security plugin. Allow requests to the store's REST API."
            )

        if status == 401:
            return False, (
                "WooCommerce rejected the request. Check your consumer key and secret are correct "
                "and have Read permission for this store."
            )

        return False, "Could not connect to your WooCommerce store. Please check the store URL."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WooCommerceResumeConfig]:
        return ResumableSourceManager[WooCommerceResumeConfig](inputs, WooCommerceResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(
        self, config: WooCommerceSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookCreationResult:
        return create_woocommerce_webhook(
            config.store_url, config.consumer_key, config.consumer_secret, team_id, webhook_url
        )

    def get_external_webhook_info(
        self, config: WooCommerceSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> ExternalWebhookInfo:
        return get_woocommerce_webhook_info(
            config.store_url, config.consumer_key, config.consumer_secret, team_id, webhook_url
        )

    def delete_webhook(
        self, config: WooCommerceSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookDeletionResult:
        return delete_woocommerce_webhook(
            config.store_url, config.consumer_key, config.consumer_secret, team_id, webhook_url
        )

    def source_for_pipeline(
        self,
        config: WooCommerceSourceConfig,
        resumable_source_manager: ResumableSourceManager[WooCommerceResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        # Only the endpoints that expose a server-side `modified_after` filter sync
        # incrementally — guard against a stale schema requesting it elsewhere.
        use_incremental = inputs.should_use_incremental_field and inputs.schema_name in INCREMENTAL_FIELDS

        resource = woocommerce_source(
            store_url=config.store_url,
            consumer_key=config.consumer_key,
            consumer_secret=config.consumer_secret,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=use_incremental,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value if use_incremental else None,
        )

        # Webhooks supplement the backfill rather than replacing it: the manager stays disabled
        # until the schema is on webhook sync and its initial pull has completed, so the first
        # sync still walks the REST API and later ones drain the pushed rows.
        webhook_source_manager = self.get_webhook_source_manager(inputs)
        webhook_enabled = (
            inputs.schema_name in WEBHOOK_SCHEMA_NAMES and async_to_sync(webhook_source_manager.webhook_enabled)()
        )

        def items():
            if webhook_enabled:
                return webhook_source_manager.get_items(table_transformer=webhook_table_transformer)
            return resource

        response = SourceResponse(
            name=resource.name,
            items=items,
            primary_keys=["id"],
            column_hints=resource.column_hints,
            # Incremental endpoints can't be reliably sorted ascending by the
            # `date_modified` cursor server-side, so we only commit the watermark
            # once the whole resource has been read (desc semantics). Webhook batches carry no
            # ordering guarantee either, so they take the same conservative path.
            sort_mode="desc" if use_incremental or webhook_enabled else "asc",
        )

        partition_key = PARTITION_FIELDS.get(inputs.schema_name)
        if partition_key:
            response.partition_count = 1
            response.partition_size = 1
            response.partition_mode = "datetime"
            response.partition_format = "month"
            response.partition_keys = [partition_key]

        return response

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WOO_COMMERCE,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            keywords=["woo"],
            label="WooCommerce",
            caption=(
                "Enter your WooCommerce store URL and REST API consumer key/secret to pull your store data "
                "into the PostHog Data warehouse. Create keys under **WooCommerce → Settings → Advanced → "
                "REST API** with at least **Read** permission."
            ),
            iconPath="/static/services/woocommerce.png",
            docsUrl="https://posthog.com/docs/cdp/sources/woocommerce",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="store_url",
                        label="Store URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="consumer_key",
                        label="Consumer key",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="ck_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="consumer_secret",
                        label="Consumer secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="cs_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                        secret=True,
                    ),
                ],
            ),
            webhookSetupCaption=WEBHOOK_SETUP_CAPTION,
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
                            "The secret set on your WooCommerce webhooks. PostHog fills this in "
                            "automatically when it registers them for you, so you only need it for "
                            "manual setup. It verifies the X-WC-Webhook-Signature header on every "
                            "delivery."
                        ),
                        secret=True,
                    ),
                ],
            ),
        )
