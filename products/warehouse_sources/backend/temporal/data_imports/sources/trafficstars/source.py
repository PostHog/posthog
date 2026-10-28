from datetime import timedelta
from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import NOT_DETECTABLE
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trafficstars import (
    TrafficStarsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trafficstars.settings import (
    ENDPOINTS,
    HISTORY_DAYS,
    INCREMENTAL_FIELDS,
    LOOKBACK,
    MERGE_ONLY,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trafficstars.trafficstars import (
    TrafficStarsResumeConfig,
    trafficstars_source,
    validate_credentials as validate_trafficstars_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TrafficStarsSource(ResumableSource[TrafficStarsSourceConfig, TrafficStarsResumeConfig]):
    codebase_detection = NOT_DETECTABLE

    lists_tables_without_credentials = True
    # TrafficStars versions each resource on its own path (v1.1 for campaigns, v2 for creatives and
    # statistics), so there is no single version to pin.
    api_docs_url = "https://docs.trafficstars.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TRAFFICSTARS

    def history_lookback_for_schema(
        self, schema_name: str, config: TrafficStarsSourceConfig | None = None
    ) -> timedelta | None:
        # Only the daily statistics are bounded by date; the lists return every row.
        return timedelta(days=HISTORY_DAYS) if schema_name == "campaign_statistics_daily" else None

    def resume_covers_run(
        self,
        *,
        incremental_or_append: bool,
        schema_name: str | None = None,
    ) -> bool:
        # The campaign list is one request, so a retry has nothing to continue from.
        return schema_name != "campaigns"

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            OAUTH2_PERMANENT_ERROR_MARKER: "TrafficStars rejected the API key. Copy it again from your TrafficStars profile.",
            "401 Client Error: Unauthorized for url: https://api.trafficstars.com": (
                "TrafficStars rejected the access token. Copy the API key again from your TrafficStars profile."
            ),
            "403 Client Error: Forbidden for url: https://api.trafficstars.com": (
                "This TrafficStars account cannot read advertiser data. Use an API key from an advertiser account."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.trafficstars.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TrafficStarsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=MERGE_ONLY, default_incremental_lookback_seconds=LOOKBACK
        )

    def validate_credentials(
        self,
        config: TrafficStarsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_trafficstars_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TrafficStarsResumeConfig]:
        return ResumableSourceManager[TrafficStarsResumeConfig](inputs, TrafficStarsResumeConfig)

    def source_for_pipeline(
        self,
        config: TrafficStarsSourceConfig,
        resumable_source_manager: ResumableSourceManager[TrafficStarsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return trafficstars_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            history_start=inputs.history_start,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TRAFFICSTARS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["traffic stars"],
            label="TrafficStars",
            caption="Sync campaigns, creatives and daily campaign statistics from your TrafficStars advertiser account.",
            docsUrl="https://posthog.com/docs/cdp/sources/trafficstars",
            iconPath="/static/services/trafficstars.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        caption="Generate one on your profile page in the TrafficStars admin panel.",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
