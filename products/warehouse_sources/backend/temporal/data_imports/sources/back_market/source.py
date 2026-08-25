from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.back_market.back_market import (
    BackMarketResumeConfig,
    back_market_source,
    validate_credentials as validate_back_market_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.back_market.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.backmarket import (
    BackMarketSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BackMarketSource(ResumableSource[BackMarketSourceConfig, BackMarketResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    # Back Market's seller API has no path/header version token — a single, unversioned
    # `www.backmarket.com/ws/` host serves every market.
    api_docs_url = "https://api.backmarket.dev/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BACKMARKET

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Your Back Market API token is invalid or has been reset. Generate a new token from your Back Office, then reconnect.",
            "403 Client Error: Forbidden": "Your Back Market API token doesn't have access to this data. Check the token in your Back Office, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.back_market.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: BackMarketSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: BackMarketSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        ok, status_code = validate_back_market_credentials(config.api_token)
        if ok:
            return True, None
        if status_code == 401:
            return False, "Invalid Back Market API token"
        return False, "Could not connect to Back Market with the provided API token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BackMarketResumeConfig]:
        return ResumableSourceManager[BackMarketResumeConfig](inputs, BackMarketResumeConfig)

    def source_for_pipeline(
        self,
        config: BackMarketSourceConfig,
        resumable_source_manager: ResumableSourceManager[BackMarketResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return back_market_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BACK_MARKET,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            keywords=["marketplace", "orders", "refurbished"],
            label="Back Market (Back Market SAS)",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Back Market seller API token to pull your orders and listings into the PostHog Data warehouse.

Generate a token from your Back Market Back Office under **Support & Technical Support**. The token stays valid until you reset your account password.""",
            iconPath="/static/services/back_market.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
