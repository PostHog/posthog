from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.usbea import UsBeaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.us_bea.settings import (
    CUSTOM_QUERY_ENDPOINT,
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.us_bea.us_bea import (
    AUTH_ERROR_MESSAGE,
    RESPONSE_TOO_LARGE_ERROR,
    parse_custom_query_params,
    us_bea_source,
    validate_credentials as validate_us_bea_credentials,
    validate_custom_query,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _has_custom_query(config: UsBeaSourceConfig) -> bool:
    return bool((config.custom_dataset_name or "").strip() and (config.custom_query_params or "").strip())


@SourceRegistry.register
class UsBeaSource(SimpleSource[UsBeaSourceConfig]):
    # Static endpoint catalog with no I/O in get_schemas - safe for public docs.
    lists_tables_without_credentials = True
    # BEA's Data Retrieval API has no version segment or header - the URI and method names
    # documented in the user guide have been stable since the API's release.
    api_docs_url = "https://apps.bea.gov/api/docs/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.USBEA

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            AUTH_ERROR_MESSAGE: "Your BEA UserID is missing or invalid. Register a free UserID at https://apps.bea.gov/api/signup/ and update the source.",
            "BEA custom query": "The custom query on this source is incomplete or invalid. Update the custom query fields on the source and retry.",
            "BEA API rejected the request": "BEA rejected the request. Check the custom query parameters against the API user guide.",
            RESPONSE_TOO_LARGE_ERROR: "The BEA response was too large to process. Narrow the custom query parameters (e.g. a smaller Year range or GeoFips selection) and retry.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.us_bea.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: UsBeaSourceConfig,
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
        config: UsBeaSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        custom_query_error = validate_custom_query(config.custom_dataset_name, config.custom_query_params)
        if custom_query_error is not None:
            return False, custom_query_error

        return validate_us_bea_credentials(config.api_key)

    def source_for_pipeline(self, config: UsBeaSourceConfig, inputs: SourceInputs) -> SourceResponse:
        if inputs.schema_name == CUSTOM_QUERY_ENDPOINT:
            custom_query_error = validate_custom_query(config.custom_dataset_name, config.custom_query_params)
            if custom_query_error is not None or not _has_custom_query(config):
                raise ValueError(custom_query_error or "BEA custom query is not configured on this source")
            assert config.custom_dataset_name is not None and config.custom_query_params is not None
            return us_bea_source(
                user_id=config.api_key,
                endpoint=CUSTOM_QUERY_ENDPOINT,
                endpoint_config=None,
                custom_dataset_name=config.custom_dataset_name.strip(),
                custom_params=parse_custom_query_params(config.custom_query_params),
            )

        endpoint_config = ENDPOINTS[inputs.schema_name]
        return us_bea_source(
            user_id=config.api_key,
            endpoint=inputs.schema_name,
            endpoint_config=endpoint_config,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.US_BEA,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="US Bureau of Economic Analysis (BEA)",
            keywords=["bea", "gdp", "economic data", "personal income"],
            caption="Sync official US economic statistics from the Bureau of Economic Analysis. Register a free UserID at [apps.bea.gov/api/signup](https://apps.bea.gov/api/signup/). To sync a table beyond the built-in ones, fill in the custom query fields with a BEA dataset name and GetData parameters from the [API user guide](https://apps.bea.gov/api/_pdf/bea_web_service_api_user_guide.pdf).",
            docsUrl="https://posthog.com/docs/cdp/sources/us-bea",
            iconPath="/static/services/us_bea.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="UserID",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="custom_dataset_name",
                        label="Custom query: dataset name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="NIPA",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="custom_query_params",
                        label="Custom query: parameters",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=False,
                        placeholder="TableName=T10101,Frequency=Q,Year=ALL",
                        secret=False,
                    ),
                ],
            ),
        )
