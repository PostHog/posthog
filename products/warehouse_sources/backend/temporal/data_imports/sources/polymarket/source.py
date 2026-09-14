from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.polymarket import (
    PolymarketSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.polymarket.polymarket import (
    PolymarketResumeConfig,
    polymarket_source,
    validate_credentials as validate_polymarket_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.polymarket.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PolymarketSource(ResumableSource[PolymarketSourceConfig, PolymarketResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Gamma exposes no version token: no path segment, header, or version param. The framework
    # default sentinel applies.
    api_docs_url = "https://docs.polymarket.com/api-reference/predictions/overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POLYMARKET

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.POLYMARKET,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Polymarket",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Polymarket's Gamma API is public, so this source needs no API key.

It syncs events, markets, series, and tags. Order books, price history, and wallet positions come from separate APIs and are not supported yet.""",
            iconPath="/static/services/polymarket.png",
            docsUrl="https://posthog.com/docs/cdp/sources/polymarket",
            keywords=["prediction market", "gamma", "trading"],
            fields=cast(list[FieldType], []),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.polymarket.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # There is no credential to fix, so a 403 means Gamma is refusing this caller.
            "403 Client Error: Forbidden for url: https://gamma-api.polymarket.com": "Polymarket refused the request. Access is restricted from some regions, so this source may not be usable from where PostHog runs.",
        }

    def get_schemas(
        self,
        config: PolymarketSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Gamma has no server-side modification filter, so INCREMENTAL_FIELDS is empty for every
        # endpoint and every table syncs full refresh.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: PolymarketSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_polymarket_credentials():
            return True, None

        return False, "Couldn't reach the Polymarket API. Try again in a few minutes."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PolymarketResumeConfig]:
        return ResumableSourceManager[PolymarketResumeConfig](inputs, PolymarketResumeConfig)

    def source_for_pipeline(
        self,
        config: PolymarketSourceConfig,
        resumable_source_manager: ResumableSourceManager[PolymarketResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return polymarket_source(
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
