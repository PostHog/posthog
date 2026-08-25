from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.bigcommerce.bigcommerce import (
    BigCommerceResumeConfig,
    bigcommerce_source,
    validate_credentials as validate_bigcommerce_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bigcommerce.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PARTITION_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bigcommerce import (
    BigCommerceSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BigCommerceSource(ResumableSource[BigCommerceSourceConfig, BigCommerceResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://developer.bigcommerce.com/api-reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BIGCOMMERCE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "BigCommerce authentication failed. Check your store hash and access token.",
            "403 Client Error": (
                "Your BigCommerce access token does not have the required OAuth scopes for this resource."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.bigcommerce.canonical_descriptions import (  # noqa: PLC0415 -- lazy import keeps this out of the hot registration path
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: BigCommerceSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: BigCommerceSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.store_hash or not config.access_token:
            return False, "Missing BigCommerce credentials"

        status = validate_bigcommerce_credentials(config.store_hash, config.access_token)

        if status == 200:
            return True, None

        # A token scoped to only some resources still passes the create-time probe; per-table
        # access is reported separately at sync time via get_non_retryable_errors.
        if status == 403 and schema_name is None:
            return True, None

        if status == 403:
            return False, "Your BigCommerce access token does not have the required OAuth scopes for this resource."

        if status == 401:
            return False, "BigCommerce authentication failed. Check your store hash and access token."

        return False, "Could not connect to your BigCommerce store. Please check the store hash."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BigCommerceResumeConfig]:
        return ResumableSourceManager[BigCommerceResumeConfig](inputs, BigCommerceResumeConfig)

    def source_for_pipeline(
        self,
        config: BigCommerceSourceConfig,
        resumable_source_manager: ResumableSourceManager[BigCommerceResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        # Only the endpoints that expose a server-side "modified since" filter sync
        # incrementally — guard against a stale schema requesting it elsewhere.
        use_incremental = inputs.should_use_incremental_field and inputs.schema_name in INCREMENTAL_FIELDS

        resource = bigcommerce_source(
            store_hash=config.store_hash,
            access_token=config.access_token,
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
            # Whether BigCommerce's `sort`/`direction` params hold a stable ascending order
            # page-to-page isn't verified against a live store. Deferring the watermark commit
            # until the whole resource has been read (desc semantics) avoids skipping rows if
            # the true order turns out not to be strictly ascending.
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
            name=SchemaExternalDataSourceType.BIG_COMMERCE,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="BigCommerce",
            caption=(
                "Enter your BigCommerce store hash and API access token to pull your store data into "
                "the PostHog Data warehouse. Create an API account under **Settings → API → "
                "Store-level API accounts** with `read-only` scope for **Products**, **Orders** and "
                "**Customers**."
            ),
            iconPath="/static/services/bigcommerce.png",
            docsUrl="https://posthog.com/docs/cdp/sources/bigcommerce",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="store_hash",
                        label="Store hash",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="abc123",
                        secret=False,
                        caption="Found in your store's control panel URL: `https://store-{store_hash}.mybigcommerce.com`.",
                    ),
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
