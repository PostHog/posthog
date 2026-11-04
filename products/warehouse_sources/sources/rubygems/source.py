import datetime
from typing import Optional, cast

from products.warehouse_sources.sources.rubygems._config import RubygemsSourceConfig
from products.warehouse_sources.sources.rubygems.rubygems import (
    TIMEFRAME_HISTORY_LOOKBACK,
    rubygems_source,
    validate_credentials as validate_rubygems_credentials,
)
from products.warehouse_sources.sources.rubygems.settings import ENDPOINTS, INCREMENTAL_FIELDS, RUBYGEMS_ENDPOINTS
from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    SimpleSource,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    detect,
)


@SourceRegistry.register
class RubygemsSource(SimpleSource[RubygemsSourceConfig]):
    codebase_detection = detect(env=("^RUBYGEMS_", "^GEM_HOST_API_KEY$"))

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://guides.rubygems.org/rubygems-org-api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RUBYGEMS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.RUBYGEMS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="RubyGems.org",
            releaseStatus=ReleaseStatus.BETA,
            caption="""Pull gem metadata and version/download history from [RubyGems.org](https://rubygems.org) into the PostHog Data warehouse.

RubyGems.org's read APIs are public, so no credentials are required. There is no list endpoint, so enter the gem names you want to track, one per line (or comma-separated). For example:

```
rails
rspec
devise
```

Each sync fetches the current metadata, version history, owners and reverse dependencies for every configured gem. These tables sync as a full refresh, because RubyGems.org has no server-side "changed since" filter for them.

The `latest_gems`, `just_updated_gems` and `timeframe_versions` tables cover all of RubyGems.org, not only your configured gems. `timeframe_versions` syncs incrementally, and its first sync reads the last 7 days.""",
            iconPath="/static/services/rubygems.png",
            docsUrl="https://posthog.com/docs/cdp/sources/rubygems",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="gems",
                        sync_setting=True,
                        label="Gems",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="rails\nrspec\ndevise",
                        secret=False,
                    ),
                ],
            ),
        )

    def history_lookback_for_schema(
        self, schema_name: str, config: RubygemsSourceConfig | None = None
    ) -> datetime.timedelta | None:
        # Only the ecosystem-wide release feed is bounded; the per-gem tables return every row.
        return TIMEFRAME_HISTORY_LOOKBACK if schema_name == "timeframe_versions" else None

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.rubygems.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,  # noqa: PLC0415
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
                # Only `timeframe_versions` takes a server-side time filter; re-fetching the per-gem
                # streams would only duplicate immutable history, so append is off too.
                supports_incremental=RUBYGEMS_ENDPOINTS[endpoint].supports_incremental,
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
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            history_start=inputs.history_start,
        )
