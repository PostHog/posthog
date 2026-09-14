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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kalshi import KalshiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.kalshi import (
    KalshiResumeConfig,
    kalshi_source,
    validate_credentials as validate_kalshi_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KalshiSource(ResumableSource[KalshiSourceConfig, KalshiResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://docs.kalshi.com/api-reference/rest-api-overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KALSHI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KALSHI,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Kalshi",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Kalshi's market data endpoints are public, so this source needs no API key.

It syncs markets, events, series, trades, and milestones. Portfolio data (your own orders, fills, and positions) needs a signed API key and is not supported yet.""",
            iconPath="/static/services/kalshi.png",
            docsUrl="https://posthog.com/docs/cdp/sources/kalshi",
            keywords=["prediction market", "event contracts", "trading"],
            fields=cast(list[FieldType], []),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # There is no credential to fix, so a 403 means Kalshi is refusing this caller (most
            # often a geo-block on the exchange). Retrying can't change that.
            "403 Client Error: Forbidden for url: https://api.elections.kalshi.com": "Kalshi refused the request. The exchange restricts access from some regions, so this source may not be usable from where PostHog runs.",
        }

    def get_schemas(
        self,
        config: KalshiSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Only `trades` carries incremental fields, so build_endpoint_schemas marks it (and only it)
        # incremental and leaves the rest full-refresh.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: KalshiSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_kalshi_credentials():
            return True, None

        return False, "Couldn't reach the Kalshi API. Try again in a few minutes."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[KalshiResumeConfig]:
        return ResumableSourceManager[KalshiResumeConfig](inputs, KalshiResumeConfig)

    def source_for_pipeline(
        self,
        config: KalshiSourceConfig,
        resumable_source_manager: ResumableSourceManager[KalshiResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return kalshi_source(
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
