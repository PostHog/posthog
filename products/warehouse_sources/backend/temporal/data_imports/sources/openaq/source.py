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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OpenAQSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.openaq.openaq import (
    OpenAQResumeConfig,
    openaq_source,
    validate_credentials as validate_openaq_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openaq.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    OPENAQ_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OpenAQSource(ResumableSource[OpenAQSourceConfig, OpenAQResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPENAQ

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OPEN_AQ,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="OpenAQ",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your OpenAQ API key to pull global air-quality data into the PostHog Data warehouse.

You can create a free API key from your [OpenAQ Explorer account](https://explore.openaq.org/account).

The free tier is limited to 60 requests per minute. The measurement tables fetch data per sensor, so syncing them against a broad set of locations makes many requests — they're off by default; enable only the sensors you need.""",
            iconPath="/static/services/openaq.png",
            docsUrl="https://posthog.com/docs/cdp/sources/openaq",
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
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.openaq.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
            # Retrying can never satisfy a credential problem, so stop the sync. Match the stable status
            # text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.openaq.org": "Your OpenAQ API key is invalid or has been revoked. Create a new key in your OpenAQ account, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.openaq.org": "Your OpenAQ API key does not have access to this data. Check the key in your OpenAQ account, then reconnect.",
        }

    def get_schemas(
        self,
        config: OpenAQSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "sensors":
                return "Sensors materialized from each location's embedded sensor list. Full refresh only"
            if OPENAQ_ENDPOINTS[endpoint].kind == "measurement":
                return "Fetched per sensor across all locations — request-heavy, so off by default"
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = OPENAQ_ENDPOINTS[endpoint]
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                detected_primary_keys=endpoint_config.primary_keys,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: OpenAQSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_openaq_credentials(config.api_key):
            return True, None

        return False, "Invalid OpenAQ API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OpenAQResumeConfig]:
        return ResumableSourceManager[OpenAQResumeConfig](inputs, OpenAQResumeConfig)

    def source_for_pipeline(
        self,
        config: OpenAQSourceConfig,
        resumable_source_manager: ResumableSourceManager[OpenAQResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return openaq_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
