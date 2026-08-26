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
from products.warehouse_sources.backend.temporal.data_imports.sources.first_promoter.first_promoter import (
    FirstPromoterResumeConfig,
    first_promoter_source,
    validate_credentials as validate_first_promoter_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.first_promoter.settings import (
    DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    INCREMENTAL_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.firstpromoter import (
    FirstPromoterSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FirstPromoterSource(ResumableSource[FirstPromoterSourceConfig, FirstPromoterResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # `/api/v2/` is a real version segment: the legacy v1 Admin API still answers on the same
    # host and is not what this source calls.
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://docs.firstpromoter.com/api-reference-v2/api-admin/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FIRSTPROMOTER

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "FirstPromoter rejected these credentials. Check the API key and account ID under Settings > Integrations > Manage API keys.",
            "403 Client Error: Forbidden for url": "This FirstPromoter API key is not allowed to read this data. Check the key under Settings > Integrations > Manage API keys.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.first_promoter.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: FirstPromoterSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=DESCRIPTIONS)
        for schema in schemas:
            schema.default_incremental_lookback_seconds = INCREMENTAL_LOOKBACK_SECONDS.get(schema.name)
        return schemas

    def validate_credentials(
        self,
        config: FirstPromoterSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_first_promoter_credentials(
            config.api_key, config.account_id, self.resolve_api_version(api_version)
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FirstPromoterResumeConfig]:
        return ResumableSourceManager[FirstPromoterResumeConfig](inputs, FirstPromoterResumeConfig)

    def source_for_pipeline(
        self,
        config: FirstPromoterSourceConfig,
        resumable_source_manager: ResumableSourceManager[FirstPromoterResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return first_promoter_source(
            api_key=config.api_key,
            account_id=config.account_id,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FIRST_PROMOTER,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="FirstPromoter",
            caption=(
                "Import promoters, referrals, commissions, payouts and promo codes from your "
                "FirstPromoter affiliate program.\n\n"
                "Find your API key and account ID in FirstPromoter under "
                "**Settings > Integrations > Manage API keys**."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/first-promoter",
            iconPath="/static/services/first_promoter.png",
            keywords=["first promoter", "affiliate", "referral"],
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
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
