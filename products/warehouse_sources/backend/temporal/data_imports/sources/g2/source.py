from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.g2.g2 import (
    G2ResumeConfig,
    g2_source,
    validate_credentials as validate_g2_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.g2.settings import (
    ENDPOINTS,
    G2_BASE_URL,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.g2 import G2SourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class G2Source(ResumableSource[G2SourceConfig, G2ResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://documentation.g2.com/docs/g2-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.G2

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.G2,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="G2 (G2.com, Inc.)",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your G2 access token to pull your product's reviews and G2's product catalog into the PostHog Data warehouse.

Create an account and generate an access token in the [G2 Developer Portal](https://my.g2.com/developers). Grant read access to the tables you want to sync:
- Products and vendors need no scope
- Reviews need the `products.reviews.read` scope

Access tokens expire one year after creation and must be regenerated.
""",
            iconPath="/static/services/g2.png",
            docsUrl="https://posthog.com/docs/cdp/sources/g2",
            keywords=["buyer intent", "reviews"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="product_id",
                        label="G2 product ID or slug",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="salesforce-sales-cloud",
                        secret=False,
                        caption="Used to sync reviews for your product. Find it in your G2 vendor dashboard, or in your product's G2 URL.",
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.g2.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            f"401 Client Error: Unauthorized for url: {G2_BASE_URL}": "Your G2 access token is invalid or has expired. Generate a new one in the G2 Developer Portal, then reconnect.",
            f"403 Client Error: Forbidden for url: {G2_BASE_URL}": "Your G2 access token does not have read access to this table. Grant it in the G2 Developer Portal, then reconnect.",
            "G2 product ID is required": "Add your G2 product ID to this source's settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: G2SourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # G2's global product catalog runs into the hundreds of thousands of rows and is full
        # refresh only, so it's opt-in rather than selected for every new connection.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, should_sync_default={"products": False})

    def validate_credentials(
        self,
        config: G2SourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        is_valid, status_code = validate_g2_credentials(config.access_token, self.resolve_api_version(api_version))
        if is_valid:
            return True, None

        if status_code == 403 and schema_name is None:
            # A genuine token that can't read categories still connects: per-endpoint scopes are
            # granted individually, so the account may only be entitled to tables the user picks.
            return True, None

        return False, "Invalid G2 access token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[G2ResumeConfig]:
        return ResumableSourceManager[G2ResumeConfig](inputs, G2ResumeConfig)

    def source_for_pipeline(
        self,
        config: G2SourceConfig,
        resumable_source_manager: ResumableSourceManager[G2ResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return g2_source(
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            product_id=config.product_id,
            api_version=self.resolve_api_version(inputs.api_version),
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
