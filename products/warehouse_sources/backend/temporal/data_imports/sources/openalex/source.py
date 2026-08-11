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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openalex import (
    OpenalexSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openalex.openalex import (
    OpenAlexResumeConfig,
    openalex_source,
    validate_credentials as validate_openalex_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openalex.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    OPENALEX_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Endpoints whose table can be narrowed with an OpenAlex filter expression, mapped to the
# config field holding it.
FILTERABLE_ENDPOINTS: dict[str, str] = {
    name: endpoint.filter_config_field
    for name, endpoint in OPENALEX_ENDPOINTS.items()
    if endpoint.filter_config_field is not None
}


@SourceRegistry.register
class OpenalexSource(ResumableSource[OpenalexSourceConfig, OpenAlexResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    # OpenAlex serves a single unversioned API at api.openalex.org: no version path segment,
    # header or param, so there is nothing to pin.
    api_docs_url = "https://developers.openalex.org/api-reference/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPENALEX

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.openalex.org": "Your OpenAlex API key is invalid or expired. Create a new key at openalex.org/settings/api and reconnect.",
            "403 Client Error: Forbidden for url: https://api.openalex.org": "OpenAlex rejected this request as needing a paid plan. Check that your filters only use fields your OpenAlex plan includes.",
            "400 Client Error: Bad Request for url: https://api.openalex.org": "OpenAlex rejected the request. Check that your filter expressions use valid OpenAlex filter fields.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.openalex.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: OpenalexSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: OpenalexSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        filters = {endpoint: self._filter_for(config, endpoint) for endpoint in FILTERABLE_ENDPOINTS}
        return validate_openalex_credentials(config.api_key, filters)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OpenAlexResumeConfig]:
        return ResumableSourceManager[OpenAlexResumeConfig](inputs, OpenAlexResumeConfig)

    def source_for_pipeline(
        self,
        config: OpenalexSourceConfig,
        resumable_source_manager: ResumableSourceManager[OpenAlexResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return openalex_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            entity_filter=self._filter_for(config, inputs.schema_name),
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

    @staticmethod
    def _filter_for(config: OpenalexSourceConfig, endpoint: str) -> Optional[str]:
        field_name = FILTERABLE_ENDPOINTS.get(endpoint)
        if field_name is None:
            return None
        value = getattr(config, field_name, None)
        return value if isinstance(value, str) else None

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OPENALEX,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="OpenAlex",
            caption="""Enter your OpenAlex API key to pull scholarly metadata into the PostHog Data warehouse.

Keys are free and take about a minute to create at [openalex.org/settings/api](https://openalex.org/settings/api).

OpenAlex indexes over 300 million works and 120 million authors, which is more than a free key's daily allowance covers. Use the filter fields to narrow the works, authors and awards tables to the records you care about, for example `authorships.institutions.lineage:i27837315` for one institution's papers. The [filtering guide](https://developers.openalex.org/guides/filtering) lists the available filter fields. Leave a filter blank to sync the whole entity.""",
            iconPath="/static/services/openalex.png",
            docsUrl="https://posthog.com/docs/cdp/sources/openalex",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["research", "scholarly", "citations", "publications"],
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
                        name="works_filter",
                        label="Works filter (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="authorships.institutions.lineage:i27837315",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="authors_filter",
                        label="Authors filter (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="last_known_institutions.id:i27837315",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="awards_filter",
                        label="Awards filter (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="funder.id:f4320306076",
                        secret=False,
                    ),
                ],
            ),
        )
