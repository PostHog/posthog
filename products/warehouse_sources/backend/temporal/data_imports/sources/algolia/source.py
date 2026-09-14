from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.algolia import (
    AlgoliaResumeConfig,
    algolia_source,
    validate_credentials as validate_algolia_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.settings import (
    ALGOLIA_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.algolia import (
    AlgoliaSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    "records": "All objects in the index, paged via the browse cursor. Full refresh only.",
    "synonyms": "Synonyms configured on the index. Full refresh only.",
    "rules": "Query rules configured on the index. Full refresh only.",
    "indices": "Every index on the application. Full refresh only.",
    "top_searches": "Most popular searches on the index with search and click/conversion counts. Full refresh only.",
    "top_hits": "Most frequent search results on the index with click and conversion counts. Full refresh only.",
    "searches_no_results": "Most frequent searches on the index that returned zero results. Full refresh only.",
    "searches_no_clicks": "Most frequent searches on the index that received no clicks. Full refresh only.",
    "ab_tests": "A/B tests configured on the application, with per-variant results. Full refresh only.",
    "conversion_rate": "Daily conversion rate on the index, with tracked search and conversion counts.",
    "add_to_cart_rate": "Daily add-to-cart rate on the index, with tracked search and add-to-cart counts.",
    "purchase_rate": "Daily purchase rate on the index, with tracked search and purchase counts.",
    "revenue": "Daily revenue attributed to searches on the index, broken down by currency.",
    "click_through_rate": "Daily click-through rate on the index, with click and tracked search counts.",
    "average_click_position": "Daily average position of clicked search results on the index.",
    "users_count": "Daily count of unique users searching the index.",
    "top_filters": "Most frequently used filter attributes on the index. Full refresh only.",
    "top_filter_values": "Most frequent filter values for each filter attribute on the index. Full refresh only.",
    "top_countries": "Countries with the most searches on the index. Full refresh only.",
    "click_positions": "Clicks per position range in the index's search results. Full refresh only.",
}


@SourceRegistry.register
class AlgoliaSource(ResumableSource[AlgoliaSourceConfig, AlgoliaResumeConfig]):
    api_docs_url = "https://www.algolia.com/doc/rest-api/search"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ALGOLIA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ALGOLIA,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Algolia",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Algolia Application ID and an API key to pull your Algolia data into the PostHog Data warehouse.

You can find your Application ID and create API keys in your [Algolia dashboard](https://dashboard.algolia.com/account/api-keys/all).

The API key needs the ACLs for the data you want to sync:
- `browse` — index records
- `settings` — synonyms and query rules
- `listIndexes` — the list of indices
- `analytics` — search, click, conversion and revenue metrics, filter and country breakdowns, and A/B tests

Set the region to match where your Algolia application is hosted. It selects the analytics host used for the analytics and A/B test tables.
""",
            iconPath="/static/services/algolia.png",
            docsUrl="https://posthog.com/docs/cdp/sources/algolia",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="application_id",
                        label="Application ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="YourApplicationID",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="index_name",
                        label="Index name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="your_index",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (analytics.algolia.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (analytics.de.algolia.com)", value="de"),
                        ],
                    ),
                ],
            ),
        )

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored API key is sent to the host derived from `application_id`, so retargeting it
        # must re-require the secret.
        return ["application_id"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Algolia returns 403 (not 401) for both a wrong Application-ID/API-key pair and a key
            # missing the ACL for an endpoint. Either way retrying can't fix it, so stop the sync.
            "403 Client Error: Forbidden for url:": "Your Algolia Application ID or API key is invalid, or the key is missing the ACL needed to sync this data. Check your credentials and key permissions in the Algolia dashboard, then reconnect.",
            "401 Client Error: Unauthorized for url:": "Your Algolia Application ID or API key is invalid. Create a new key in the Algolia dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: AlgoliaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # `merge_only` covers every endpoint because Algolia restates recent days as late
        # events arrive, so a re-read has to update those rows rather than append a copy.
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            merge_only=ENDPOINTS,
            descriptions=_ENDPOINT_DESCRIPTIONS,
            should_sync_default={name: cfg.should_sync_default for name, cfg in ALGOLIA_ENDPOINTS.items()},
        )

    def validate_credentials(
        self,
        config: AlgoliaSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_algolia_credentials(
            application_id=config.application_id,
            api_key=config.api_key,
            index_name=config.index_name,
            schema_name=schema_name,
            region=config.region,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AlgoliaResumeConfig]:
        return ResumableSourceManager[AlgoliaResumeConfig](inputs, AlgoliaResumeConfig)

    def source_for_pipeline(
        self,
        config: AlgoliaSourceConfig,
        resumable_source_manager: ResumableSourceManager[AlgoliaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return algolia_source(
            endpoint=inputs.schema_name,
            application_id=config.application_id,
            api_key=config.api_key,
            index_name=config.index_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            manager=resumable_source_manager,
            region=config.region,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            incremental_field=inputs.incremental_field,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,  # noqa: PLC0415
        )

        return CANONICAL_DESCRIPTIONS
