from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import WooCommerceSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PARTITION_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.woocommerce import (
    WooCommerceResumeConfig,
    validate_credentials as validate_woocommerce_credentials,
    woocommerce_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WooCommerceSource(ResumableSource[WooCommerceSourceConfig, WooCommerceResumeConfig]):
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://woocommerce.github.io/woocommerce-rest-api-docs/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WOOCOMMERCE

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "WooCommerce authentication failed. Please check your consumer key and secret.",
            "403 Client Error": "WooCommerce authentication failed or the API key lacks read permission for this resource.",
        }

    def get_schemas(
        self,
        config: WooCommerceSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: WooCommerceSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not config.store_url or not config.consumer_key or not config.consumer_secret:
            return False, "Missing WooCommerce credentials"

        status = validate_woocommerce_credentials(
            config.store_url, config.consumer_key, config.consumer_secret, team_id
        )

        if status == 200:
            return True, None

        # A valid key may legitimately lack read scope for the probe endpoint. Accept that at
        # source-create time; sync-time 403s are caught by `get_non_retryable_errors`.
        if status == 403 and schema_name is None:
            return True, None

        if status == 403:
            return False, "WooCommerce API key lacks read permission for this resource. Please check the key scope."

        if status == 401:
            return False, "WooCommerce authentication failed. Please check your consumer key and secret."

        return False, "Could not connect to your WooCommerce store. Please check the store URL."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WooCommerceResumeConfig]:
        return ResumableSourceManager[WooCommerceResumeConfig](inputs, WooCommerceResumeConfig)

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

        response = SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=["id"],
            column_hints=resource.column_hints,
            # Incremental endpoints can't be reliably sorted ascending by the
            # `date_modified` cursor server-side, so we only commit the watermark
            # once the whole resource has been read (desc semantics).
            sort_mode="desc" if use_incremental else "asc",
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
        )
