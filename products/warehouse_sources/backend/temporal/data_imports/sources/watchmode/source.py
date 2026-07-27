from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.watchmode import (
    WatchmodeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.watchmode.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.watchmode.watchmode import (
    WatchmodeResumeConfig,
    validate_credentials as validate_watchmode_credentials,
    watchmode_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WatchmodeSource(ResumableSource[WatchmodeSourceConfig, WatchmodeResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://api.watchmode.com/docs/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WATCHMODE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.watchmode.com": "Your Watchmode API key is invalid or expired. Please generate a new key and update the source.",
            "403 Client Error: Forbidden for url: https://api.watchmode.com": "Your Watchmode plan does not allow access to this endpoint. Please check your plan and try again.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.watchmode.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: WatchmodeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: WatchmodeSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_watchmode_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WatchmodeResumeConfig]:
        return ResumableSourceManager[WatchmodeResumeConfig](inputs, WatchmodeResumeConfig)

    def source_for_pipeline(
        self,
        config: WatchmodeSourceConfig,
        resumable_source_manager: ResumableSourceManager[WatchmodeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return watchmode_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WATCHMODE,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Watchmode",
            caption="Sync Watchmode's streaming catalog: titles, releases, streaming sources, regions, networks and genres.\n\nYou can find your API key in your [Watchmode dashboard](https://api.watchmode.com/). Syncs count against your Watchmode monthly request quota.",
            keywords=["streaming", "movies", "tv"],
            docsUrl="https://posthog.com/docs/cdp/sources/watchmode",
            iconPath="/static/services/watchmode.png",
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
