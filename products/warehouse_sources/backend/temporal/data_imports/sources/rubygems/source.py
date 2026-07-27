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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rubygems import (
    RubygemsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rubygems.rubygems import (
    rubygems_source,
    validate_credentials as validate_rubygems_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rubygems.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    RUBYGEMS_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RubygemsSource(SimpleSource[RubygemsSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://guides.rubygems.org/rubygems-org-api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RUBYGEMS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RUBYGEMS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="RubyGems.org",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Pull gem metadata and version/download history from [RubyGems.org](https://rubygems.org) into the PostHog Data warehouse.

RubyGems.org's read APIs are public, so no credentials are required. There is no list endpoint, so enter the gem names you want to track, one per line (or comma-separated). For example:

```
rails
rspec
devise
```

Each sync fetches the current metadata and full version history for every configured gem. RubyGems.org has no server-side "changed since" filter, so all tables sync as a full refresh.""",
            iconPath="/static/services/rubygems.png",
            docsUrl="https://posthog.com/docs/cdp/sources/rubygems",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="gems",
                        label="Gems",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="rails\nrspec\ndevise",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.rubygems.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # RubyGems.org's read APIs are unauthenticated, so there are no credential errors to
        # permanently fail on. A missing gem surfaces as a 404 and is skipped per-gem during sync.
        return {}

    def get_schemas(
        self,
        config: RubygemsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # RubyGems.org exposes no server-side timestamp filter, so no stream is truly
                # incremental; re-fetching would only duplicate immutable history, so append is off too.
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=RUBYGEMS_ENDPOINTS[endpoint].should_sync_default,
                description=RUBYGEMS_ENDPOINTS[endpoint].description,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: RubygemsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_rubygems_credentials(config.gems)

    def source_for_pipeline(self, config: RubygemsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return rubygems_source(
            endpoint=inputs.schema_name,
            gems_raw=config.gems,
            logger=inputs.logger,
        )
