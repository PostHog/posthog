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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.heyreach import (
    HeyReachSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.heyreach.heyreach import (
    HeyReachResumeConfig,
    heyreach_source,
    validate_credentials as validate_heyreach_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.heyreach.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HeyReachSource(ResumableSource[HeyReachSourceConfig, HeyReachResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    api_docs_url = "https://documenter.getpostman.com/view/23808049/2sA2xb5F75"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HEYREACH

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.heyreach.io": (
                "HeyReach rejected the API key. Create a new key in HeyReach under "
                "Settings > Integrations > HeyReach API and update this source."
            ),
            "403 Client Error: Forbidden for url: https://api.heyreach.io": (
                "Your HeyReach API key does not have access to this data. Create a new key in "
                "HeyReach under Settings > Integrations > HeyReach API and update this source."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.heyreach.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: HeyReachSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: HeyReachSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_heyreach_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HeyReachResumeConfig]:
        return ResumableSourceManager[HeyReachResumeConfig](inputs, HeyReachResumeConfig)

    def source_for_pipeline(
        self,
        config: HeyReachSourceConfig,
        resumable_source_manager: ResumableSourceManager[HeyReachResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return heyreach_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.HEYREACH,
            category=DataWarehouseSourceCategory.SALES,
            label="HeyReach",
            caption=(
                "Import campaigns, leads, LinkedIn sender accounts, inbox conversations, and daily "
                "outreach stats from HeyReach. Create an API key in HeyReach under "
                "Settings > Integrations > HeyReach API."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/heyreach",
            iconPath="/static/services/heyreach.png",
            keywords=["linkedin outreach", "sales engagement", "heyreach"],
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
                    ),
                ],
            ),
        )
