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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.worldbank import (
    WorldBankSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.world_bank.settings import (
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    PRIMARY_KEYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.world_bank.world_bank import (
    WorldBankResumeConfig,
    parse_indicator_codes,
    validate_credentials as validate_world_bank_credentials,
    world_bank_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WorldBankSource(ResumableSource[WorldBankSourceConfig, WorldBankResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # v2 is the only live version; v1 was shut down in June 2020. The version is a path segment
    # on every request the source makes.
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://datahelpdesk.worldbank.org/knowledgebase/topics/125589-developer-information"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WORLDBANK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WORLD_BANK,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="World Bank Open Data",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["world bank", "indicators", "gdp", "economic data"],
            caption="""Pull country-level development statistics from the [World Bank Indicators API](https://datahelpdesk.worldbank.org/knowledgebase/topics/125589-developer-information) into the PostHog Data warehouse.

The API is open, so no credentials are required. The World Bank publishes around 16,000 indicator series, which is far too much to sync wholesale, so enter the indicator codes you want (up to 50), one per line. For example:

```
SP.POP.TOTL
NY.GDP.PCAP.CD
IT.NET.USER.ZS
```

You can look codes up in the `indicators` table or on [data.worldbank.org](https://data.worldbank.org/indicator). Observations for every code you enter land in a single `indicator_data` table.

The API has no "changed since" filter, and the World Bank revises historical values on each quarterly release, so every table syncs as a full refresh.""",
            iconPath="/static/services/world_bank.png",
            docsUrl="https://posthog.com/docs/cdp/sources/world-bank",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="indicator_codes",
                        label="Indicator codes",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="SP.POP.TOTL\nNY.GDP.PCAP.CD\nIT.NET.USER.ZS",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.world_bank.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # The API is unauthenticated, so there are no credential errors. What can permanently
        # fail a sync is an indicator code the API does not recognize: it answers HTTP 200 with an
        # error envelope, which the resource's required data selector rejects.
        return {
            "Required data_selector '[1]' matched nothing in the response": "The World Bank Indicators API returned an error instead of data. Check that every indicator code you entered is valid.",
            # A code list that is empty or over the cap can't be fixed by retrying.
            "World Bank source misconfigured": "Check the indicator codes on this source: the list is empty or has more codes than a single source can sync.",
        }

    def get_schemas(
        self,
        config: WorldBankSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # No endpoint exposes a server-side "changed since" filter, so every table is full
        # refresh only. The indicator data endpoint does accept a `date=YYYY:YYYY` window, but
        # the World Bank rewrites historical values on each release, so a windowed sync would
        # silently miss revisions.
        return build_endpoint_schemas(ENDPOINTS, {}, names, descriptions=ENDPOINT_DESCRIPTIONS)

    def validate_credentials(
        self,
        config: WorldBankSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_world_bank_credentials(
            parse_indicator_codes(config.indicator_codes),
            self.resolve_api_version(api_version),
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WorldBankResumeConfig]:
        return ResumableSourceManager[WorldBankResumeConfig](inputs, WorldBankResumeConfig)

    def source_for_pipeline(
        self,
        config: WorldBankSourceConfig,
        resumable_source_manager: ResumableSourceManager[WorldBankResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        endpoint = inputs.schema_name
        api_version = self.resolve_api_version(inputs.api_version)
        indicator_codes = parse_indicator_codes(config.indicator_codes)

        return SourceResponse(
            name=endpoint,
            items=lambda: world_bank_source(
                endpoint=endpoint,
                indicator_codes=indicator_codes,
                api_version=api_version,
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                resumable_source_manager=resumable_source_manager,
            ),
            primary_keys=PRIMARY_KEYS[endpoint],
            # The resume checkpoint advances after every yielded page, so each page has to be
            # durable before the next one moves the bookmark past it. Each yielded item is already
            # a whole API page, so chunk_size=1 flushes it to Delta on its own rather than letting
            # several pages sit in the batcher's buffer — a mid-sync failure would otherwise resume
            # past the buffered pages and finish the full-refresh table with silent gaps.
            chunk_size=1,
        )
