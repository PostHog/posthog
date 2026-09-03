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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.housecallpro import (
    HousecallProSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.housecall_pro.housecall_pro import (
    HousecallProResumeConfig,
    housecall_pro_source,
    validate_credentials as validate_housecall_pro_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.housecall_pro.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HousecallProSource(ResumableSource[HousecallProSourceConfig, HousecallProResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # No URL path segment, version header, or dated query param — the vendor's API has no
    # meaningful version scheme to pin.
    api_docs_url = "https://docs.housecallpro.com/docs/housecall-public-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HOUSECALLPRO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HOUSECALL_PRO,
            category=DataWarehouseSourceCategory.CRM,
            label="Housecall Pro",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Housecall Pro API key to pull your jobs, customers, and invoices into the PostHog Data warehouse.

API access needs a MAX plan. An account admin can generate a key under **My Apps → All Apps → API Key Management** — choose read-only access for a sync-only key.""",
            iconPath="/static/services/housecall_pro.png",
            docsUrl="https://posthog.com/docs/cdp/sources/housecall-pro",
            keywords=["field service", "fsm"],
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
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.housecall_pro.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.housecallpro.com": "Your Housecall Pro API key is invalid or has been revoked. Generate a new key under My Apps → API Key Management, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.housecallpro.com": "Housecall Pro rejected this request. API access needs a MAX plan and a key with the right access level — check both, then reconnect.",
        }

    def get_schemas(
        self,
        config: HousecallProSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: HousecallProSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_housecall_pro_credentials(config.api_key):
            return True, None

        return False, "Invalid Housecall Pro API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HousecallProResumeConfig]:
        return ResumableSourceManager[HousecallProResumeConfig](inputs, HousecallProResumeConfig)

    def source_for_pipeline(
        self,
        config: HousecallProSourceConfig,
        resumable_source_manager: ResumableSourceManager[HousecallProResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return housecall_pro_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
