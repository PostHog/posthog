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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ShopWiredSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.shopwired.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SHOPWIRED_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopwired.shopwired import (
    ShopWiredResumeConfig,
    shopwired_source,
    validate_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ShopWiredSource(ResumableSource[ShopWiredSourceConfig, ShopWiredResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SHOPWIRED

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SHOP_WIRED,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="ShopWired",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your ShopWired API credentials to pull your store data into the PostHog Data warehouse.

You can create an API key and secret under **Account > API keys** in your [ShopWired](https://www.shopwired.co.uk) account. The credentials grant read access to your products, categories, brands, tags, customers, orders, and vouchers.
""",
            iconPath="/static/services/shopwired.png",
            docsUrl="https://posthog.com/docs/cdp/sources/shopwired",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="api_secret",
                        label="API secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.shopwired.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.ecommerceapi.uk": "Your ShopWired API key or secret is invalid or has been revoked. Generate new credentials under Account > API keys, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.ecommerceapi.uk": "Your ShopWired API credentials do not have access to this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: ShopWiredSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Only orders expose a server-side created-date filter (`from`), so every other endpoint is
        # full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=endpoint in INCREMENTAL_FIELDS,
                supports_append=endpoint in INCREMENTAL_FIELDS,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: ShopWiredSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key/secret pair is account-wide, so a single probe validates access to every schema.
        return validate_credentials(config.api_key, config.api_secret)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ShopWiredResumeConfig]:
        return ResumableSourceManager[ShopWiredResumeConfig](inputs, ShopWiredResumeConfig)

    def source_for_pipeline(
        self,
        config: ShopWiredSourceConfig,
        resumable_source_manager: ResumableSourceManager[ShopWiredResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in SHOPWIRED_ENDPOINTS:
            raise ValueError(f"Unknown ShopWired schema '{inputs.schema_name}'")

        return shopwired_source(
            api_key=config.api_key,
            api_secret=config.api_secret,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )
