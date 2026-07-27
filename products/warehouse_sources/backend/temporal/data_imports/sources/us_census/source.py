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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.uscensus import (
    USCensusSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.us_census.settings import (
    CUSTOM_QUERY_ENDPOINT,
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.us_census.us_census import (
    AUTH_ERROR_MESSAGE,
    RESPONSE_TOO_LARGE_PREFIX,
    parse_custom_variables,
    us_census_source,
    validate_credentials as validate_us_census_credentials,
    validate_custom_query,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _has_custom_query(config: USCensusSourceConfig) -> bool:
    return bool(
        (config.custom_dataset or "").strip()
        and (config.custom_variables or "").strip()
        and (config.custom_geography or "").strip()
    )


@SourceRegistry.register
class USCensusSource(SimpleSource[USCensusSourceConfig]):
    # Static endpoint catalog with no I/O in get_schemas — safe for public docs.
    lists_tables_without_credentials = True
    # The Census Data API is unversioned; datasets are versioned by vintage in the URL path.
    api_docs_url = "https://www.census.gov/data/developers/guidance/api-user-guide.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.USCENSUS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            AUTH_ERROR_MESSAGE: "Your US Census API key was rejected. Request a free key at https://api.census.gov/data/key_signup.html and update the source.",
            "unknown variable": "One of the requested variables does not exist in the selected dataset. Check the dataset's variable list at https://api.census.gov/data.html.",
            "unsupported geography": "The requested geography is not supported by the selected dataset. Check the dataset's geography list at https://api.census.gov/data.html.",
            "US Census custom query": "The custom query on this source is incomplete or invalid. Update the custom query fields on the source and retry.",
            RESPONSE_TOO_LARGE_PREFIX: "The query returned more data than a single sync can hold. Narrow the custom query with fewer variables or a smaller geography (e.g. an in= filter).",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.us_census.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: USCensusSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        endpoint_names = list(ENDPOINTS)
        if _has_custom_query(config):
            endpoint_names.append(CUSTOM_QUERY_ENDPOINT)
        return build_endpoint_schemas(endpoint_names, INCREMENTAL_FIELDS, names, descriptions=ENDPOINT_DESCRIPTIONS)

    def validate_credentials(
        self,
        config: USCensusSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        custom_query_error = validate_custom_query(
            config.custom_dataset, config.custom_variables, config.custom_geography
        )
        if custom_query_error is not None:
            return False, custom_query_error

        return validate_us_census_credentials(config.api_key)

    def source_for_pipeline(self, config: USCensusSourceConfig, inputs: SourceInputs) -> SourceResponse:
        if inputs.schema_name == CUSTOM_QUERY_ENDPOINT:
            custom_query_error = validate_custom_query(
                config.custom_dataset, config.custom_variables, config.custom_geography
            )
            if custom_query_error is not None or not _has_custom_query(config):
                raise ValueError(custom_query_error or "US Census custom query is not configured on this source")
            assert config.custom_dataset is not None and config.custom_variables is not None
            assert config.custom_geography is not None
            return us_census_source(
                api_key=config.api_key,
                endpoint=CUSTOM_QUERY_ENDPOINT,
                dataset=config.custom_dataset.strip().strip("/"),
                variables=parse_custom_variables(config.custom_variables),
                geography=config.custom_geography.strip(),
                geography_filter=(config.custom_geography_filter or "").strip() or None,
                # The geography columns of an arbitrary query aren't known ahead of time,
                # and the table is full refresh only, so no primary keys are declared.
                primary_keys=None,
            )

        endpoint = ENDPOINTS[inputs.schema_name]
        return us_census_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            dataset=endpoint.dataset,
            variables=endpoint.variables,
            geography=endpoint.geography,
            predicates=endpoint.predicates,
            primary_keys=list(endpoint.primary_keys),
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.US_CENSUS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="US Census",
            keywords=["census", "acs", "american community survey", "demographics", "government"],
            caption="Sync official US Census Bureau statistics. Get a free API key at [api.census.gov](https://api.census.gov/data/key_signup.html). To sync a dataset beyond the built-in tables, fill in the custom query fields using the dataset directory at [api.census.gov/data.html](https://api.census.gov/data.html).",
            docsUrl="https://posthog.com/docs/cdp/sources/us-census",
            iconPath="/static/services/us_census.svg",
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
                    SourceFieldInputConfig(
                        name="custom_dataset",
                        label="Custom query: dataset path",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2024/acs/acs5",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="custom_variables",
                        label="Custom query: variables (get)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="NAME,B01001_001E",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="custom_geography",
                        label="Custom query: geography (for)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="state:*",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="custom_geography_filter",
                        label="Custom query: parent geography (in)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="state:06",
                        secret=False,
                    ),
                ],
            ),
        )
