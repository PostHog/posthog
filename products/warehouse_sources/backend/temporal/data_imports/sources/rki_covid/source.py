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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rkicovid import (
    RKICovidSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rki_covid.rki_covid import (
    rki_covid_source,
    validate_connection,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rki_covid.settings import RKI_COVID_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


def validate_history_days(history_days: Optional[int]) -> str | None:
    if history_days is not None and history_days < 1:
        return "History window (days) must be a positive number, or left empty for the full history"
    return None


@SourceRegistry.register
class RKICovidSource(SimpleSource[RKICovidSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://api.corona-zahlen.org/docs/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RKICOVID

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # The API is community-maintained; a 404 means the endpoint was moved or removed
            # upstream, which retrying can never fix.
            "404 Client Error: Not Found for url: https://api.corona-zahlen.org": "The RKI COVID-19 API no longer serves this endpoint. The API is community-maintained and may have changed; check https://api.corona-zahlen.org/docs/ for its current status.",
            "RKI COVID-19 API error [unexpected_response]": "The RKI COVID-19 API returned an unexpected response. The API is community-maintained; check https://api.corona-zahlen.org/docs/ for its current status.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.rki_covid.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: RKICovidSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # The API has no server-side timestamp cursor (history endpoints only take a relative
        # `:days` window), so every table is full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint.name,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                detected_primary_keys=endpoint.primary_keys,
                description=endpoint.description,
            )
            for endpoint in RKI_COVID_ENDPOINTS.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: RKICovidSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        days_error = validate_history_days(config.history_days)
        if days_error:
            return False, days_error

        if validate_connection():
            return True, None

        return (
            False,
            "The RKI COVID-19 API (api.corona-zahlen.org) is not reachable right now. It's a public community-run service; please try again later.",
        )

    def source_for_pipeline(self, config: RKICovidSourceConfig, inputs: SourceInputs) -> SourceResponse:
        days_error = validate_history_days(config.history_days)
        if days_error:
            raise ValueError(f"RKI COVID-19 source misconfigured: {days_error}")

        return rki_covid_source(
            endpoint=inputs.schema_name,
            history_days=config.history_days,
            logger=inputs.logger,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RKI_COVID,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="RKI COVID-19",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["covid", "corona", "coronavirus", "rki", "germany", "public health"],
            caption="""Pull German COVID-19 statistics (nationwide, per state, and per district) into the PostHog Data warehouse from the public RKI COVID-19 API at [api.corona-zahlen.org](https://api.corona-zahlen.org).

No credentials are needed. The API is a community-maintained wrapper (by Marlon Lückert) over published Robert Koch-Institut figures, not an official RKI service.

Optionally limit the history tables to the last N days; leave empty to sync the full history.""",
            iconPath="/static/services/rki_covid.png",
            docsUrl="https://posthog.com/docs/cdp/sources/rki-covid",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="history_days",
                        label="History window (days)",
                        type=SourceFieldInputConfigType.NUMBER,
                        required=False,
                        placeholder="Leave empty for full history",
                        secret=False,
                    ),
                ],
            ),
        )
