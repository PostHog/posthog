from typing import Optional, cast

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

from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_commerce.adobe_commerce import (
    ADMIN_TOKEN_RETRYABLE_ERROR,
    HOST_NOT_ALLOWED_ERROR,
    HTTPS_REQUIRED_ERROR,
    INCOMPLETE_CREDENTIALS_ERROR,
    PAGINATION_LIMIT_ERROR,
    AdobeCommerceCredentials,
    AdobeCommerceResumeConfig,
    adobe_commerce_source,
    validate_credentials as validate_adobe_commerce_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_commerce.settings import (
    ADOBE_COMMERCE_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.adobecommerce import (
    AdobeCommerceSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

CAPTION = """Enter your Adobe Commerce (Magento 2) store URL and API credentials to pull your store data into the PostHog Data warehouse.

The recommended way to connect is an integration access token: in the admin go to **System > Extensions > Integrations**, create an integration, grant it read access to Sales, Catalog, Customers and Carts, then activate it and copy the **Access Token**.

On Magento 2.4.4 and later, integration tokens are rejected as bearer tokens until you set **Stores > Configuration > Services > OAuth > Access Token Expiration > Allow OAuth Access Tokens to be used as standalone Bearer tokens** to **Yes**. If you can't change that setting, connect with an admin username and password instead and PostHog will mint a short-lived admin token for each sync."""


def _credentials_from_config(config: AdobeCommerceSourceConfig) -> AdobeCommerceCredentials:
    auth = config.auth_method
    if auth.selection == "admin":
        return AdobeCommerceCredentials(method="admin", username=auth.username, password=auth.password)
    return AdobeCommerceCredentials(method="access_token", access_token=auth.access_token)


@SourceRegistry.register
class AdobeCommerceSource(ResumableSource[AdobeCommerceSourceConfig, AdobeCommerceResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    # Magento's REST namespace has been `/V1` since Magento 2.0 and isn't a version merchants can
    # pick, so there is nothing meaningful to pin.
    api_docs_url = "https://developer.adobe.com/commerce/webapi/rest/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ADOBECOMMERCE

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored token/password is sent to `store_url`; retargeting it must re-require them.
        return ["store_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ADOBE_COMMERCE,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            keywords=["magento", "magento 2", "adobe"],
            label="Adobe Commerce (Magento)",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=CAPTION,
            iconPath="/static/services/adobe_commerce.png",
            docsUrl="https://posthog.com/docs/cdp/sources/adobe-commerce",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="store_url",
                        label="Store URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://store.example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="store_code",
                        label="Store code (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="default",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication method",
                        required=True,
                        defaultValue="access_token",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="Integration access token (recommended)",
                                value="access_token",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="access_token",
                                            label="Access token",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="Admin username and password",
                                value="admin",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="username",
                                            label="Admin username",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=False,
                                            placeholder="",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="password",
                                            label="Admin password",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # The URL carries the merchant's own host, so match on the status prefix only.
        return {
            "401 Client Error": "Adobe Commerce rejected the credentials. Check the access token (or admin login) is valid and the integration has read access to this data. On Magento 2.4.4 and later, also enable 'Allow OAuth Access Tokens to be used as standalone Bearer tokens'.",
            "403 Client Error": "Your Adobe Commerce integration does not have read access to this data. Grant it under System > Extensions > Integrations, then reconnect.",
            HOST_NOT_ALLOWED_ERROR: "The Adobe Commerce store URL is not allowed. Use your store's public URL.",
            HTTPS_REQUIRED_ERROR: "The Adobe Commerce store URL must use HTTPS so your credentials aren't sent in the clear. Update the store URL and reconnect.",
            INCOMPLETE_CREDENTIALS_ERROR: "Adobe Commerce credentials are incomplete. Please re-enter them and reconnect.",
            PAGINATION_LIMIT_ERROR: "Adobe Commerce kept returning pages without signalling the end of the collection. This usually means the store's REST API is misconfigured — check the store URL and store code.",
        }

    def get_retryable_errors(self) -> set[str]:
        # The admin token exchange already retries 429/5xx at the transport level (the tracked
        # session); this is only raised once that budget is exhausted, and re-minting later
        # recovers on its own. Keep it out of error tracking rather than paging it as a bug.
        return {ADMIN_TOKEN_RETRYABLE_ERROR}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_commerce.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AdobeCommerceSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Sales and catalog rows are rewritten in place (an order's status advances, a product's
        # price changes), so append mode would duplicate them — merge is the only incremental mode.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=ENDPOINTS)

    def validate_credentials(
        self,
        config: AdobeCommerceSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_adobe_commerce_credentials(
            store_url=config.store_url,
            store_code=config.store_code,
            credentials=_credentials_from_config(config),
            schema_name=schema_name,
            team_id=team_id,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AdobeCommerceResumeConfig]:
        return ResumableSourceManager[AdobeCommerceResumeConfig](inputs, AdobeCommerceResumeConfig)

    def source_for_pipeline(
        self,
        config: AdobeCommerceSourceConfig,
        resumable_source_manager: ResumableSourceManager[AdobeCommerceResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in ADOBE_COMMERCE_ENDPOINTS:
            raise ValueError(f"Unknown Adobe Commerce schema '{inputs.schema_name}'")

        return adobe_commerce_source(
            store_url=config.store_url,
            store_code=config.store_code,
            credentials=_credentials_from_config(config),
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field_name=inputs.incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
