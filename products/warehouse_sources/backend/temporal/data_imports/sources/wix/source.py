from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wix import WixSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.wix.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.wix.wix import (
    WixResumeConfig,
    check_endpoint_permissions,
    validate_credentials as validate_wix_credentials,
    wix_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WixSource(ResumableSource[WixSourceConfig, WixResumeConfig]):
    # Wix versions each API family in its path rather than the account as a whole, so there is no
    # single account-wide version to pin.
    api_docs_url = "https://dev.wix.com/docs/rest/api-reference"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WIX

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://www.wixapis.com": "Wix rejected this API key. Create a new key in the Wix API Key Manager and reconnect the source.",
            "403 Client Error: Forbidden for url: https://www.wixapis.com": "This API key is missing a permission for this table. Grant it in the Wix API Key Manager and reconnect the source.",
            "428 Client Error": "Wix could not find this site. Check the site ID matches the site you want to sync.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.WIX,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Wix",
            caption="""Enter a Wix API key and the ID of the site you want to sync, to pull your orders, products, contacts, members, and blog posts into the PostHog Data warehouse.

Create an API key in the [Wix API Key Manager](https://manage.wix.com/account/api-keys) and give it read access to the areas you want to sync: eCommerce Orders, Stores, Contacts, Members, and Blog. Only an account owner or a co-owner with full permissions can create one.

Find the site ID in the Wix dashboard URL for your site, in the part after `/dashboard/`. A key that is missing a permission still connects, and the table picker marks the tables it cannot read.""",
            iconPath="/static/services/wix.png",
            docsUrl="https://posthog.com/docs/cdp/sources/wix",
            keywords=["wix", "website builder", "ecommerce"],
            releaseStatus=ReleaseStatus.ALPHA,
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
                        caption="Create this in the Wix API Key Manager under your account settings.",
                    ),
                    SourceFieldInputConfig(
                        name="site_id",
                        label="Site ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="12345678-1234-1234-1234-123456789012",
                        secret=False,
                        caption="The site's ID, shown in your Wix dashboard URL after `/dashboard/`.",
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.wix.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: WixSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: WixSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_wix_credentials(config.api_key, config.site_id)

    def get_endpoint_permissions(
        self, config: WixSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        return check_endpoint_permissions(config.api_key, config.site_id, endpoints)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WixResumeConfig]:
        return ResumableSourceManager[WixResumeConfig](inputs, WixResumeConfig)

    def source_for_pipeline(
        self,
        config: WixSourceConfig,
        resumable_source_manager: ResumableSourceManager[WixResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in ENDPOINTS:
            raise ValueError(f"Unknown Wix endpoint: {inputs.schema_name}")

        return wix_source(
            api_key=config.api_key,
            site_id=config.site_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
