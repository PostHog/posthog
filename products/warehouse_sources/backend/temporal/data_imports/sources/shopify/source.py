import functools
from datetime import date
from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.schema_flags import is_schema_flag_enabled
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    FieldType,
    ResumableSource,
    VersionDeprecation,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import RowFilterColumn
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shopify import (
    ShopifySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.constants import (
    CREATED_AT,
    SHOPIFY_API_VERSION_2025_10,
    SHOPIFY_API_VERSION_2026_07,
    SHOPIFY_GRAPHQL_OBJECTS,
    resolve_schema_name,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.settings import ENDPOINT_CONFIGS
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify import (
    CREATED_AT_FILTER_OPERATORS,
    SHOPIFY_ACCESS_TOKEN_APP_NOT_INSTALLED_ERROR,
    SHOPIFY_ACCESS_TOKEN_AUTH_ERROR,
    SHOPIFY_ACCESS_TOKEN_INVALID_CLIENT_ERROR,
    SHOPIFY_ACCESS_TOKEN_IS_APP_SECRET_ERROR,
    SHOPIFY_ACCESS_TOKEN_SHOP_NOT_PERMITTED_ERROR,
    SHOPIFY_ACCESS_TOKEN_UNSUPPORTED_GRANT_ERROR,
    SHOPIFY_GRAPHQL_ACCESS_DENIED_ERROR,
    SHOPIFY_GRAPHQL_NOT_FOUND_ERROR_MATCH,
    SHOPIFY_GRAPHQL_PII_PLAN_RESTRICTED_ERROR,
    SHOPIFY_GRAPHQL_UNAUTHORIZED_ERROR_MATCH,
    SHOPIFY_GRAPHQL_UNAUTHORIZED_ERROR_MESSAGE,
    SHOPIFY_MISSING_CREDENTIALS_ERROR,
    SHOPIFY_PAYMENT_REQUIRED_ERROR_MATCH,
    SHOPIFY_PAYMENT_REQUIRED_ERROR_MESSAGE,
    SHOPIFY_STORE_NOT_FOUND_ERROR,
    ShopifyPermissionError,
    ShopifyResumeConfig,
    check_endpoint_permissions as check_shopify_endpoint_permissions,
    missing_permissions_message,
    shopify_source,
    validate_credentials as validate_shopify_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

WAREHOUSE_SHOPIFY_PARALLEL_READ_FLAG = "warehouse-shopify-parallel-read"


def _is_parallel_read_enabled(team_id: int, schema_id: str) -> bool:
    schema = ExternalDataSchema.objects.filter(team_id=team_id, id=schema_id).select_related("source").first()
    return schema is not None and is_schema_flag_enabled(schema, WAREHOUSE_SHOPIFY_PARALLEL_READ_FLAG)


@SourceRegistry.register
class ShopifySource(ResumableSource[ShopifySourceConfig, ShopifyResumeConfig]):
    codebase_detection = detect(
        env=(
            "^SHOPIFY_",
            "^PUBLIC_STORE_DOMAIN$",
            "^PUBLIC_STOREFRONT_API_TOKEN$",
            "^PRIVATE_STOREFRONT_API_TOKEN$",
            "^PUBLIC_STOREFRONT_ID$",
            "^PUBLIC_CHECKOUT_DOMAIN$",
            "^PUBLIC_CUSTOMER_ACCOUNT_API_CLIENT_ID$",
            "^GATSBY_MYSHOPIFY_URL$",
        ),
        script_hosts=("cdn.shopify.com", "sdks.shopifycdn.com"),
        npm=(
            "@shopify/shopify-api",
            "shopify-api-node",
            "@shopify/shopify-app-remix",
            "@shopify/shopify-app-react-router",
            "@shopify/shopify-app-express",
            "@shopify/hydrogen",
            "@shopify/app-bridge",
            "@shopify/app-bridge-react",
            "@shopify/storefront-api-client",
            "@shopify/admin-api-client",
            "@shopify/graphql-client",
            "@shopify/shopify-app-session-storage",
            "@shopify/shopify-app-session-storage-prisma",
            "@shopify/shopify-app-session-storage-memory",
            "@shopify/shopify-app-session-storage-postgresql",
            "@shopify/shopify-app-session-storage-redis",
            "@shopify/shopify-app-session-storage-kv",
            "@shopify/shopify-app-session-storage-mongodb",
            "@shopify/shopify-app-session-storage-dynamodb",
            "@shopify/shopify-app-session-storage-sqlite",
            "@shopify/shopify-app-session-storage-drizzle",
            "@shopify/shopify-app-session-storage-mysql",
            "@shopify/cli",
            "@shopify/app",
            "@shopify/theme",
            "@shopify/cli-hydrogen",
            "@shopify/oxygen-cli",
            "@shopify/hydrogen-react",
            "@shopify/remix-oxygen",
            "@shopify/mini-oxygen",
            "@shopify/oxygen-workers-types",
            "@shopify/hydrogen-codegen",
            "@shopify/api-codegen-preset",
            "@shopify/hydrogen-ui-alpha",
            "@shopify/storefront-kit-react",
            "@shopify/app-bridge-types",
            "@shopify/app-bridge-ui-types",
            "@shopify/app-bridge-utils",
            "@shopify/polaris",
            "@shopify/polaris-types",
            "@shopify/discount-app-components",
            "@shopify/ui-extensions",
            "@shopify/ui-extensions-react",
            "@shopify/checkout-ui-extensions",
            "@shopify/checkout-ui-extensions-react",
            "@shopify/admin-ui-extensions",
            "@shopify/admin-ui-extensions-react",
            "@shopify/post-purchase-ui-extensions",
            "@shopify/post-purchase-ui-extensions-react",
            "@shopify/retail-ui-extensions",
            "@shopify/retail-ui-extensions-react",
            "@shopify/customer-account-ui-extensions",
            "@shopify/customer-account-ui-extensions-react",
            "@shopify/web-pixels-extension",
            "@shopify/shopify_function",
            "@shopify/scripts-checkout-apis",
            "@shopify/buy-button-js",
            "shopify-buy",
            "@shopify/checkout-sheet-kit",
            "@shopify/checkout-kit",
            "@shopify/shop-minis-react",
            "@shopify/shop-minis-platform",
            "@shopify/shop-minis-platform-sdk",
            "@shopify/koa-shopify-auth",
            "@shopify/koa-shopify-webhooks",
            "@shopify/koa-shopify-graphql-proxy",
            "@shopify/slate-tools",
            "gatsby-source-shopify",
            "@nuxtjs/shopify",
            "nuxt-shopify",
        ),
        pypi=("shopifyapi", "shopifyapp", "shopifyql", "django-shopify-auth"),
        cargo=("shopify_function", "shopify_function_wasm_api"),
        cocoapods=("Mobile-Buy-SDK", "ShopifyCheckoutSheetKit", "ShopifyCheckoutKit"),
        composer=(
            "shopify/shopify-api",
            "shopify/shopify-app-php",
            "phpclassic/php-shopify",
            "kyon147/laravel-shopify",
            "osiset/laravel-shopify",
            "gnikyt/basic-shopify-api",
            "osiset/basic-shopify-api",
        ),
        go=("github.com/bold-commerce/go-shopify", "github.com/r0busta/go-shopify-graphql"),
        hex=("shopify",),
        maven=("com.shopify.mobilebuysdk:buy3", "com.shopify:checkout-sheet-kit", "com.shopify:checkout-kit"),
        pub=("shopify_flutter",),
        rubygems=(
            "shopify_api",
            "shopify_app",
            "omniauth-shopify-oauth2",
            "shopify-cli",
            "shopify_theme",
            "shopify_graphql",
        ),
        swiftpm=(
            "github.com/shopify/mobile-buy-sdk-ios",
            "github.com/shopify/checkout-sheet-kit-swift",
            "github.com/shopify/checkout-kit-swift",
        ),
    )

    supported_versions = (SHOPIFY_API_VERSION_2025_10, SHOPIFY_API_VERSION_2026_07)
    default_version = SHOPIFY_API_VERSION_2026_07
    api_docs_url = "https://shopify.dev/docs/api/release-notes"
    # Shopify keeps each quarterly version accessible for about 12 months, then falls forward to
    # the oldest accessible version instead of erroring — so a pin left on 2025-10 silently moves
    # rather than failing loudly.
    deprecated_versions = (VersionDeprecation(version=SHOPIFY_API_VERSION_2025_10, sunset_at=date(2026, 10, 16)),)

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supports_row_filters = True

    def row_filter_columns_for_schema(self, schema_name: str) -> tuple[RowFilterColumn, ...]:
        endpoint_config = ENDPOINT_CONFIGS.get(resolve_schema_name(schema_name))
        if endpoint_config is None or endpoint_config.created_at_search_field is None:
            return ()
        return (RowFilterColumn(name=CREATED_AT, data_type="timestamp", operators=CREATED_AT_FILTER_OPERATORS),)

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
            # Retrying cannot recover; the user must re-enter valid credentials.
            SHOPIFY_ACCESS_TOKEN_AUTH_ERROR: SHOPIFY_ACCESS_TOKEN_AUTH_ERROR,
            # 4xx `invalid_client` — the client ID or secret does not match a Shopify app.
            SHOPIFY_ACCESS_TOKEN_INVALID_CLIENT_ERROR: SHOPIFY_ACCESS_TOKEN_INVALID_CLIENT_ERROR,
            # 4xx `unsupported_grant_type` — the app can't use the client_credentials grant, so
            # the user needs a Dev Dashboard app instead of a legacy custom app.
            SHOPIFY_ACCESS_TOKEN_UNSUPPORTED_GRANT_ERROR: SHOPIFY_ACCESS_TOKEN_UNSUPPORTED_GRANT_ERROR,
            # 4xx `shop_not_permitted`: the store is not in the app's Shopify organization, so
            # minting a token fails regardless of the credentials entered.
            SHOPIFY_ACCESS_TOKEN_SHOP_NOT_PERMITTED_ERROR: SHOPIFY_ACCESS_TOKEN_SHOP_NOT_PERMITTED_ERROR,
            # 4xx `app_not_installed`: the credentials are valid but the app is not installed on
            # the store, so minting a token fails until the user installs it. Retrying cannot fix it.
            SHOPIFY_ACCESS_TOKEN_APP_NOT_INSTALLED_ERROR: SHOPIFY_ACCESS_TOKEN_APP_NOT_INSTALLED_ERROR,
            # The user pasted the app's client secret into the Admin API access token field. No
            # request is made, so this never reaches Shopify and retrying cannot change it.
            SHOPIFY_ACCESS_TOKEN_IS_APP_SECRET_ERROR: SHOPIFY_ACCESS_TOKEN_IS_APP_SECRET_ERROR,
            # Neither authentication method was filled in, so there is nothing to authenticate with.
            SHOPIFY_MISSING_CREDENTIALS_ERROR: SHOPIFY_MISSING_CREDENTIALS_ERROR,
            # 404 from the same endpoint — no store at this subdomain. Retrying cannot
            # recover; the user must correct the store id.
            SHOPIFY_STORE_NOT_FOUND_ERROR: SHOPIFY_STORE_NOT_FOUND_ERROR,
            # GraphQL "Access denied for <field> field" — the access token is missing the
            # scope required to read this resource. The scope can't change on retry, so fail
            # fast and tell the user to reconnect with the required permissions.
            SHOPIFY_GRAPHQL_ACCESS_DENIED_ERROR: (
                "Your Shopify access token is missing the permissions required to read some of your data. "
                "Please reconnect your Shopify integration and grant the requested access scopes."
            ),
            # GraphQL "This app is not approved to access the <object> object" — the store's
            # Shopify plan doesn't grant apps access to customer PII. No scope or reconnect can
            # fix this; the merchant must upgrade their plan or stop syncing tables with PII.
            SHOPIFY_GRAPHQL_PII_PLAN_RESTRICTED_ERROR: (
                "Your Shopify plan doesn't allow apps to access customer personal data (PII) such as "
                "names, addresses, emails, and phone numbers. Upgrade to the Shopify, Advanced, or Plus "
                "plan, or turn off syncing the tables that include customer PII."
            ),
            # 402 Payment Required from the Admin API — the store is frozen for an unpaid
            # bill. Retrying cannot recover; the shop owner must settle their Shopify balance.
            SHOPIFY_PAYMENT_REQUIRED_ERROR_MATCH: SHOPIFY_PAYMENT_REQUIRED_ERROR_MESSAGE,
            # 401 from the Admin API GraphQL endpoint itself — the token was valid at mint
            # time but Shopify now rejects it. Retrying cannot recover; the user must
            # reconnect their integration.
            SHOPIFY_GRAPHQL_UNAUTHORIZED_ERROR_MATCH: SHOPIFY_GRAPHQL_UNAUTHORIZED_ERROR_MESSAGE,
            # 404 from the Admin API GraphQL endpoint — no live store answers at the configured
            # address. Retrying cannot recover; the user must correct the store id, the same fix
            # as the token endpoint's 404 above.
            SHOPIFY_GRAPHQL_NOT_FOUND_ERROR_MATCH: SHOPIFY_STORE_NOT_FOUND_ERROR,
        }

    def get_retryable_errors(self) -> set[str]:
        # These are the messages `ShopifyRetryableError` carries once `_make_paginated_shopify_
        # request`'s `execute` exhausts its own tenacity retries (5 attempts, exponential backoff
        # honoring Shopify's throttle refill time — retried alongside transient `ConnectionError`/
        # `Timeout`) and re-raises. Surviving all 5 attempts means the rate limit or upstream blip
        # is still live, but Temporal retries the whole activity and it's self-recovering, so keep
        # it out of error tracking as noise.
        return {
            "Shopify: rate limit exceeded",
            "Shopify: internal error",
            "Shopify: connection broken while reading response",
            # `_get_shopify_access_token` raises this once its own tenacity retries (same 5-attempt
            # budget) are exhausted for a 429/5xx from the OAuth token endpoint — the same
            # self-recovering contract as the GraphQL messages above.
            "Failed to retrieve Shopify access token:",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SHOPIFY,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            iconPath="/static/services/shopify.png",
            caption=(
                "Pull your Shopify store data into the PostHog Data warehouse. Pick how you want "
                "to connect. A Dev Dashboard app works when the app and the store belong to the "
                "same Shopify organization. When they cannot, use an Admin API access token from "
                "an app installed on the store. The docs walk through both options."
            ),
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
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication method",
                        required=True,
                        defaultValue="client_credentials",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="Client ID and secret",
                                value="client_credentials",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="shopify_client_id",
                                            label="Client ID",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=False,
                                            placeholder="client-id",
                                            caption=(
                                                "From a Shopify Dev Dashboard app. The app and the "
                                                "store must belong to the same Shopify organization."
                                            ),
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="shopify_client_secret",
                                            label="Secret",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="client-secret",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="Admin API access token",
                                value="access_token",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="shopify_access_token",
                                            label="Admin API access token",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="shpat_...",
                                            caption=(
                                                "Use this when your store cannot join the same "
                                                "Shopify organization as the app. Find it on the "
                                                "app's API credentials page in your store admin."
                                            ),
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.GA,
        )

    def validate_credentials(
        self,
        config: ShopifySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # No schema_name → just probe the token, so connecting isn't blocked by a table the user
        # may not sync. With schema_name → also check that one resource's read scope.
        resources = [schema_name] if schema_name is not None else None
        try:
            if validate_shopify_credentials(
                config.shopify_store_id,
                config.auth_method.shopify_client_id,
                config.auth_method.shopify_client_secret,
                resources,
                self.resolve_api_version(api_version),
                shopify_access_token=config.auth_method.shopify_access_token,
            ):
                return True, None
            return False, "Invalid Shopify credentials"
        except ShopifyPermissionError as e:
            return False, missing_permissions_message(e.missing_permissions)
        except Exception as e:
            return False, str(e)

    def get_endpoint_permissions(
        self, config: ShopifySourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        return check_shopify_endpoint_permissions(
            config.shopify_store_id,
            config.auth_method.shopify_client_id,
            config.auth_method.shopify_client_secret,
            endpoints,
            self.resolve_api_version(api_version),
            shopify_access_token=config.auth_method.shopify_access_token,
        )

    def get_schemas(
        self,
        config: ShopifySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
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
            shopify_client_id=config.auth_method.shopify_client_id,
            shopify_client_secret=config.auth_method.shopify_client_secret,
            shopify_access_token=config.auth_method.shopify_access_token,
            graphql_object_name=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            db_incremental_field_earliest_value=inputs.db_incremental_field_earliest_value,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            row_filters=inputs.row_filters,
            use_parallel_read=functools.partial(_is_parallel_read_enabled, inputs.team_id, inputs.schema_id),
        )
