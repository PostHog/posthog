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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ShopifySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.constants import SHOPIFY_GRAPHQL_OBJECTS
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.settings import ENDPOINT_CONFIGS
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify import (
    SHOPIFY_ACCESS_TOKEN_AUTH_ERROR,
    SHOPIFY_GRAPHQL_ACCESS_DENIED_ERROR,
    SHOPIFY_PAYMENT_REQUIRED_ERROR_MATCH,
    SHOPIFY_PAYMENT_REQUIRED_ERROR_MESSAGE,
    ShopifyPermissionError,
    ShopifyResumeConfig,
    check_endpoint_permissions as check_shopify_endpoint_permissions,
    missing_permissions_message,
    shopify_source,
    validate_credentials as validate_shopify_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ShopifySource(ResumableSource[ShopifySourceConfig, ShopifyResumeConfig]):
    supported_versions = ("2025-10",)
    default_version = "2025-10"
    api_docs_url = "https://shopify.dev/docs/api/release-notes"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SHOPIFY

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 4xx from Shopify's OAuth token endpoint — invalid/revoked app credentials.
            # Retrying cannot recover; the user must reconnect the integration.
            SHOPIFY_ACCESS_TOKEN_AUTH_ERROR: SHOPIFY_ACCESS_TOKEN_AUTH_ERROR,
            # GraphQL "Access denied for <field> field" — the access token is missing the
            # scope required to read this resource. The scope can't change on retry, so fail
            # fast and tell the user to reconnect with the required permissions.
            SHOPIFY_GRAPHQL_ACCESS_DENIED_ERROR: (
                "Your Shopify access token is missing the permissions required to read some of your data. "
                "Please reconnect your Shopify integration and grant the requested access scopes."
            ),
            # 402 Payment Required from the Admin API — the store is frozen for an unpaid
            # bill. Retrying cannot recover; the shop owner must settle their Shopify balance.
            SHOPIFY_PAYMENT_REQUIRED_ERROR_MATCH: SHOPIFY_PAYMENT_REQUIRED_ERROR_MESSAGE,
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SHOPIFY,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            iconPath="/static/services/shopify.png",
            caption="""Enter your Shopify credentials to automatically pull your Shopify data into the PostHog Data warehouse.""",
            docsUrl="https://posthog.com/docs/data-warehouse/sources/shopify",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="shopify_store_id",
                        label="Store id",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-store",
                        caption=(
                            "Your store subdomain — the `my-store` in `my-store.myshopify.com`. "
                            "Pasting the full store URL works too."
                        ),
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="shopify_client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="client-id",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="shopify_client_secret",
                        label="Secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="shpss_...",
                        secret=True,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.GA,
        )

    def validate_credentials(
        self, config: ShopifySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # No schema_name → just probe the token, so connecting isn't blocked by a table the user
        # may not sync. With schema_name → also check that one resource's read scope.
        resources = [schema_name] if schema_name is not None else None
        try:
            if validate_shopify_credentials(
                config.shopify_store_id, config.shopify_client_id, config.shopify_client_secret, resources
            ):
                return True, None
            return False, "Invalid Shopify credentials"
        except ShopifyPermissionError as e:
            return False, missing_permissions_message(e.missing_permissions)
        except Exception as e:
            return False, str(e)

    def get_endpoint_permissions(
        self, config: ShopifySourceConfig, team_id: int, endpoints: list[str]
    ) -> dict[str, str | None]:
        return check_shopify_endpoint_permissions(
            config.shopify_store_id, config.shopify_client_id, config.shopify_client_secret, endpoints
        )

    def get_schemas(
        self,
        config: ShopifySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = []
        for obj in SHOPIFY_GRAPHQL_OBJECTS.values():
            endpoint_config = ENDPOINT_CONFIGS.get(obj.name)
            if not endpoint_config:
                raise ValueError(f"No endpoint config found for {obj.name}")
            schemas.append(
                SourceSchema(
                    name=obj.display_name or obj.name,
                    supports_incremental=len(endpoint_config.fields) > 0,
                    supports_append=len(endpoint_config.fields) > 0,
                    incremental_fields=endpoint_config.fields,
                )
            )
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ShopifyResumeConfig]:
        return ResumableSourceManager[ShopifyResumeConfig](inputs, ShopifyResumeConfig)

    def source_for_pipeline(
        self,
        config: ShopifySourceConfig,
        resumable_source_manager: ResumableSourceManager[ShopifyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return shopify_source(
            shopify_store_id=config.shopify_store_id,
            shopify_client_id=config.shopify_client_id,
            shopify_client_secret=config.shopify_client_secret,
            graphql_object_name=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            db_incremental_field_earliest_value=inputs.db_incremental_field_earliest_value,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
