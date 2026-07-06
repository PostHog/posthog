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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import NewYorkTimesSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.new_york_times.new_york_times import (
    NewYorkTimesResumeConfig,
    new_york_times_source,
    validate_credentials as validate_nyt_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.new_york_times.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    NEW_YORK_TIMES_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NewYorkTimesSource(ResumableSource[NewYorkTimesSourceConfig, NewYorkTimesResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NEWYORKTIMES

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.NEW_YORK_TIMES,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="New York Times",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption=(
                "Enter your New York Times API key to pull New York Times content into the PostHog Data warehouse.\n\n"
                "Create a free developer account and register an app at the "
                "[NYT Developer Network](https://developer.nytimes.com/), then enable the APIs you want to sync "
                "(Article Search, Most Popular, Top Stories) on your app to get an API key.\n\n"
                "Note: NYT enforces tight rate limits (≈10 requests/minute, 4,000/day), so syncs — especially "
                "Article Search — are intentionally throttled."
            ),
            iconPath="/static/services/new_york_times.png",
            docsUrl="https://posthog.com/docs/cdp/sources/new-york-times",
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
                        name="article_search_query",
                        label="Article Search query (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="e.g. climate",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.new_york_times.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or unauthorized API key surfaces as an HTTPError from `_fetch_page`. Retrying can
            # never satisfy a credential problem, so stop the sync. Match the stable status text and base
            # host, not the per-request path/query (which is stripped to avoid leaking the api-key).
            "401 Client Error: Unauthorized for url: https://api.nytimes.com": "Your New York Times API key is invalid or unauthorized. Create a new key in the NYT Developer Network and reconnect.",
            "403 Client Error: Forbidden for url: https://api.nytimes.com": "Your New York Times API key does not have access to this API. Enable the required API on your app in the NYT Developer Network, then reconnect.",
        }

    def get_schemas(
        self,
        config: NewYorkTimesSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = NEW_YORK_TIMES_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                detected_primary_keys=endpoint_config.primary_keys,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: NewYorkTimesSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_nyt_credentials(config.api_key):
            return True, None

        return False, "Invalid New York Times API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[NewYorkTimesResumeConfig]:
        return ResumableSourceManager[NewYorkTimesResumeConfig](inputs, NewYorkTimesResumeConfig)

    def source_for_pipeline(
        self,
        config: NewYorkTimesSourceConfig,
        resumable_source_manager: ResumableSourceManager[NewYorkTimesResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return new_york_times_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            query=config.article_search_query or None,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
