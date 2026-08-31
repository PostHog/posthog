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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.meteostat import (
    MeteostatSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.meteostat.meteostat import (
    NO_STATIONS_ERROR,
    MeteostatResumeConfig,
    _parse_station_ids,
    meteostat_source,
    start_date_error,
    validate_station,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.meteostat.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MAX_STATIONS,
    UNITS_OPTIONS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MeteostatSource(ResumableSource[MeteostatSourceConfig, MeteostatResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # No meaningful vendor versioning: the RapidAPI-hosted JSON API has never published a
    # version token (path segment, header, or query param) to pin.
    api_docs_url = "https://dev.meteostat.net/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.METEOSTAT

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid RapidAPI key. Check the key and reconnect the source.",
            "403 Client Error": (
                "This RapidAPI key isn't subscribed to the Meteostat API. Subscribe on RapidAPI and reconnect."
            ),
            NO_STATIONS_ERROR: "Add at least one weather station ID in the source settings to sync this table.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.meteostat.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MeteostatSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: MeteostatSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        stations = _parse_station_ids(config.station_ids)
        if not stations:
            return False, "Add at least one weather station ID to sync."
        if len(stations) > MAX_STATIONS:
            return False, f"Too many station IDs. List at most {MAX_STATIONS}."

        error = start_date_error(config.start_date)
        if error is not None:
            return False, error

        return validate_station(config.api_key, stations[0])

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MeteostatResumeConfig]:
        return ResumableSourceManager[MeteostatResumeConfig](inputs, MeteostatResumeConfig)

    def source_for_pipeline(
        self,
        config: MeteostatSourceConfig,
        resumable_source_manager: ResumableSourceManager[MeteostatResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return meteostat_source(
            api_key=config.api_key,
            station_ids=config.station_ids,
            units=config.units,
            start_date=config.start_date,
            endpoint_name=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.METEOSTAT,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Meteostat",
            keywords=["weather", "climate", "historical weather"],
            caption=(
                "Sync historical weather and climate data for weather stations from the Meteostat JSON API "
                "(hosted on RapidAPI). Get a free API key by subscribing to the "
                "[Meteostat API listing](https://rapidapi.com/meteostat/api/meteostat/) on RapidAPI — the free "
                "plan includes 500 requests per month.\n\n"
                "Meteostat has no account-scoped list of stations, so list the "
                "[weather station IDs](https://meteostat.net) you want to sync."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/meteostat",
            iconPath="/static/services/meteostat.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="RapidAPI key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="station_ids",
                        label="Weather station IDs",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="10637, 71508",
                        secret=False,
                        caption=f"Comma-separated list of Meteostat station IDs. Up to {MAX_STATIONS} stations.",
                    ),
                    SourceFieldSelectConfig(
                        name="units",
                        label="Unit system",
                        required=True,
                        defaultValue="metric",
                        options=[
                            SourceFieldSelectConfigOption(label=label, value=value) for value, label in UNITS_OPTIONS
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2015-01-01",
                        secret=False,
                        caption=(
                            "Earliest day to sync (YYYY-MM-DD). Defaults to 2015-01-01 to keep the initial sync "
                            "within a typical RapidAPI free-tier quota."
                        ),
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
