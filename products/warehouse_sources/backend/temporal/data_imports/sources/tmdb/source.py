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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TMDbSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tmdb.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    TMDB_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tmdb.tmdb import (
    TMDbResumeConfig,
    tmdb_source,
    validate_credentials as validate_tmdb_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TMDbSource(ResumableSource[TMDbSourceConfig, TMDbResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TMDB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TM_DB,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="TMDb",
            caption="""Enter your TMDB API key to pull movie, TV, and people catalog data into the PostHog Data warehouse.

Create a free API key (v3 auth) in your [TMDB account settings](https://www.themoviedb.org/settings/api). Commercial use requires a separate license from TMDB.""",
            iconPath="/static/services/tmdb.png",
            docsUrl="https://posthog.com/docs/cdp/sources/tmdb",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
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

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked TMDB API key surfaces as a 401 when `_fetch` calls
            # `raise_for_status()`. Retrying can't fix a credential problem, so stop the sync.
            "401 Client Error: Unauthorized for url: https://api.themoviedb.org": "Your TMDB API key is invalid or has been revoked. Create a new key in your TMDB account settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: TMDbSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # TMDB v3 list endpoints expose no server-side updated-after filter, so every table is
                # full refresh only.
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=TMDB_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: TMDbSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_tmdb_credentials(config.api_key)

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.tmdb.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TMDbResumeConfig]:
        return ResumableSourceManager[TMDbResumeConfig](inputs, TMDbResumeConfig)

    def source_for_pipeline(
        self,
        config: TMDbSourceConfig,
        resumable_source_manager: ResumableSourceManager[TMDbResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return tmdb_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
