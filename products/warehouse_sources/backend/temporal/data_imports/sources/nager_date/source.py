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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.nagerdate import (
    NagerDateSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.nager_date.nager_date import (
    NagerDateResumeConfig,
    nager_date_source,
    parse_country_codes,
    validate_credentials as validate_nager_date_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.nager_date.settings import (
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    PRIMARY_KEYS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NagerDateSource(ResumableSource[NagerDateSourceConfig, NagerDateResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # The v3 API is deprecated (sunset 2027-01-31); v4 is the current generally available version
    # and is what every request in nager_date.py sends (the `/api/v4/` path segment).
    supported_versions = ("v4",)
    default_version = "v4"
    api_docs_url = "https://date.nager.at/scalar"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NAGERDATE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.NAGER_DATE,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Nager.Date",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["holidays", "public holidays", "calendar"],
            caption="""Pull public holiday data from the free [Nager.Date](https://date.nager.at) API into the PostHog Data warehouse.

The API is open, so no credentials are required. Enter the ISO 3166-1 alpha-2 country codes you want to track, one per line or comma separated. For example:

```
US
GB
DE
```

A holidays table like this is commonly joined against event, order, or traffic timestamps by date and country to explain dips and seasonality.

The API only serves a rolling window of years around today, and it has no "changed since" filter, so every table syncs as a full refresh on each run. This also picks up holiday corrections the source publishes after the fact.""",
            iconPath="/static/services/nager_date.png",
            docsUrl="https://posthog.com/docs/cdp/sources/nager-date",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="country_codes",
                        label="Country codes",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="US\nGB\nDE",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.nager_date.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # The API is unauthenticated, so there are no credential errors. What can permanently
        # fail a sync is a country code list that's empty, malformed, or over the per-source cap.
        return {
            "Nager.Date source misconfigured": "Check the country codes on this source: the list is empty, invalid, or has more codes than a single source can sync.",
        }

    def get_schemas(
        self,
        config: NagerDateSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # No endpoint exposes a server-side "changed since" filter, so every table is full
        # refresh only. That's also how retroactive holiday corrections get picked up.
        return build_endpoint_schemas(ENDPOINTS, {}, names, descriptions=ENDPOINT_DESCRIPTIONS)

    def validate_credentials(
        self,
        config: NagerDateSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_nager_date_credentials(parse_country_codes(config.country_codes))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[NagerDateResumeConfig]:
        return ResumableSourceManager[NagerDateResumeConfig](inputs, NagerDateResumeConfig)

    def source_for_pipeline(
        self,
        config: NagerDateSourceConfig,
        resumable_source_manager: ResumableSourceManager[NagerDateResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        endpoint = inputs.schema_name
        country_codes = parse_country_codes(config.country_codes)

        return SourceResponse(
            name=endpoint,
            items=lambda: nager_date_source(
                endpoint=endpoint,
                country_codes=country_codes,
                resumable_source_manager=resumable_source_manager,
            ),
            primary_keys=PRIMARY_KEYS[endpoint],
        )
