from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rewardful import (
    RewardfulSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rewardful.rewardful import (
    RewardfulResumeConfig,
    rewardful_source,
    validate_credentials as validate_rewardful_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rewardful.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RewardfulSource(ResumableSource[RewardfulSourceConfig, RewardfulResumeConfig]):
    codebase_detection = detect(env=("^REWARDFUL_",), script_hosts=("r.wdfl.co",))

    lists_tables_without_credentials = True
    api_docs_url = "https://developers.rewardful.com/rest-api/overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REWARDFUL

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Rewardful rejected the API secret. Copy it again from Company settings in Rewardful, then reconnect the source.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.rewardful.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: RewardfulSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: RewardfulSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_rewardful_credentials(config.api_secret)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RewardfulResumeConfig]:
        return ResumableSourceManager[RewardfulResumeConfig](inputs, RewardfulResumeConfig)

    def source_for_pipeline(
        self,
        config: RewardfulSourceConfig,
        resumable_source_manager: ResumableSourceManager[RewardfulResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return rewardful_source(
            api_secret=config.api_secret,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.REWARDFUL,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            keywords=["affiliate", "referral"],
            label="Rewardful",
            caption="Sync affiliates, referrals, commissions and payouts from your Rewardful affiliate program.",
            docsUrl="https://posthog.com/docs/cdp/sources/rewardful",
            iconPath="/static/services/rewardful.png",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_secret",
                        label="API secret",
                        caption="Found under Company settings in Rewardful. The secret can also change data, but PostHog only reads with it.",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
