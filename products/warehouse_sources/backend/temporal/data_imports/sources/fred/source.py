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
from products.warehouse_sources.backend.temporal.data_imports.sources.fred.fred import (
    SERIES_ID_PATTERN,
    FredResumeConfig,
    fred_source,
    parse_series_ids,
    validate_credentials as validate_fred_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fred.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fred import FredSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FredSource(ResumableSource[FredSourceConfig, FredResumeConfig]):
    api_docs_url = "https://fred.stlouisfed.org/docs/api/fred/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FRED

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "FRED authentication failed": "Your FRED API key is invalid or is not registered. Request a key at fred.stlouisfed.org and reconnect.",
            "FRED rejected the request": "FRED rejected the request. Check that every series ID in your source settings exists on fred.stlouisfed.org.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FRED,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="FRED",
            keywords=["federal reserve", "economic data", "st louis fed", "macro"],
            caption="""Pull US and international economic time series from FRED, the Federal Reserve Bank of St. Louis database, into the PostHog Data warehouse.

Request a free API key at [fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html). FRED has around 800,000 series, so pick the ones you want: a series ID is the code at the end of its FRED page URL, such as `UNRATE` for the unemployment rate or `CPIAUCSL` for CPI.""",
            iconPath="/static/services/fred.png",
            docsUrl="https://posthog.com/docs/cdp/sources/fred",
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
                        name="series_ids",
                        label="Series IDs",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="UNRATE, CPIAUCSL, GDPC1, DGS10",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.fred.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: FredSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: FredSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        series_ids = parse_series_ids(config.series_ids)
        if not series_ids:
            return False, "Enter at least one FRED series ID"

        invalid = next((series_id for series_id in series_ids if not SERIES_ID_PATTERN.match(series_id)), None)
        if invalid is not None:
            return False, f"{invalid} is not a valid FRED series ID. IDs look like UNRATE or CPIAUCSL."

        return validate_fred_credentials(config.api_key, series_ids[0])

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FredResumeConfig]:
        return ResumableSourceManager[FredResumeConfig](inputs, FredResumeConfig)

    def source_for_pipeline(
        self,
        config: FredSourceConfig,
        resumable_source_manager: ResumableSourceManager[FredResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return fred_source(
            api_key=config.api_key,
            series_ids=parse_series_ids(config.series_ids),
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
