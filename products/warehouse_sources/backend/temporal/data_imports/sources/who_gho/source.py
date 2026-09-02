from datetime import date, datetime
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.whogho import WhoGhoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.who_gho.settings import (
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PRIMARY_KEYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.who_gho.who_gho import (
    WhoGhoResumeConfig,
    parse_indicator_codes,
    validate_credentials as validate_who_gho_credentials,
    who_gho_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WhoGhoSource(ResumableSource[WhoGhoSourceConfig, WhoGhoResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog -- safe for public docs
    # OData v4, with no version token in the URL, headers, or docs -- the API has never had a
    # second version.
    api_docs_url = "https://www.who.int/data/gho/info/gho-odata-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WHOGHO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WHO_GHO,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="World Health Organization Global Health Observatory (GHO)",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["who", "health", "gho", "indicators"],
            caption="""Pull public health statistics from the [WHO Global Health Observatory](https://www.who.int/data/gho) into the PostHog Data warehouse.

The API is open, so no credentials are required. WHO publishes over 2,000 indicator series, which is far too much to sync wholesale, so enter the indicator codes you want, one per line. For example:

```
WHOSIS_000001
WHOSIS_000002
NCD_BMI_30A
```

You can look codes up in the `indicators` table or in the [GHO OData API documentation](https://www.who.int/data/gho/info/gho-odata-api). Observations for every code you enter land in a single `indicator_data` table.

WHO refreshes each indicator on its own publication cycle, typically annually, so a daily or weekly sync is more than enough to pick up changes.""",
            iconPath="/static/services/who_gho.png",
            docsUrl="https://posthog.com/docs/cdp/sources/who-gho",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="indicator_codes",
                        label="Indicator codes",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="WHOSIS_000001\nWHOSIS_000002\nNCD_BMI_30A",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.who_gho.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # The API is unauthenticated, so there are no credential errors. What can permanently
        # fail a sync is an indicator code the API does not recognize (404) or a code list that
        # is empty or over the per-source cap -- neither resolves by retrying.
        return {
            "404 Client Error: Not Found for url": "The WHO GHO API did not recognize one of the configured indicator codes. Check the indicator codes on this source.",
            "WHO GHO source misconfigured": "Check the indicator codes on this source: the list is empty or has more codes than a single source can sync.",
        }

    def get_schemas(
        self,
        config: WhoGhoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=ENDPOINT_DESCRIPTIONS)

    def validate_credentials(
        self,
        config: WhoGhoSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_who_gho_credentials(parse_indicator_codes(config.indicator_codes))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WhoGhoResumeConfig]:
        return ResumableSourceManager[WhoGhoResumeConfig](inputs, WhoGhoResumeConfig)

    def source_for_pipeline(
        self,
        config: WhoGhoSourceConfig,
        resumable_source_manager: ResumableSourceManager[WhoGhoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        endpoint = inputs.schema_name
        indicator_codes = parse_indicator_codes(config.indicator_codes)

        since: Optional[str] = None
        last_value = inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None
        if isinstance(last_value, datetime):
            since = last_value.date().isoformat()
        elif isinstance(last_value, date):
            since = last_value.isoformat()

        return SourceResponse(
            name=endpoint,
            items=lambda: who_gho_source(
                endpoint=endpoint,
                indicator_codes=indicator_codes,
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                resumable_source_manager=resumable_source_manager,
                should_use_incremental_field=inputs.should_use_incremental_field,
                since=since,
            ),
            primary_keys=PRIMARY_KEYS[endpoint],
            # The resume checkpoint advances after every yielded page, so each page has to be
            # durable before the next one moves the bookmark past it.
            chunk_size=1,
        )
