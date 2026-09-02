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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openmeteo import (
    OpenMeteoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.open_meteo.open_meteo import (
    OpenMeteoResumeConfig,
    open_meteo_source,
    validate_credentials as validate_open_meteo_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.open_meteo.settings import (
    ENDPOINTS,
    OPEN_METEO_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

CAPTION = """Pull weather and air quality data from [Open-Meteo](https://open-meteo.com) into the PostHog Data warehouse, so you can join it against your own events.

Open-Meteo is free for non-commercial use and needs no API key. Commercial plans issue a key that also routes requests to Open-Meteo's reserved-capacity hosts, so add one below if you have it.

Open-Meteo has no endpoint that lists locations, so enter one location per line as `latitude,longitude`. An optional label is allowed: `latitude,longitude,label`. For example:

```
51.5074,-0.1278,London
40.7128,-74.0060,New York
```

The archive tables backfill hourly and daily history from the start date you set, then sync incrementally. The forecast and air quality tables always hold the current rolling window, because their values are revised on every model run.

Free use is licensed CC BY 4.0 and requires attribution to Open-Meteo."""


@SourceRegistry.register
class OpenMeteoSource(ResumableSource[OpenMeteoSourceConfig, OpenMeteoResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    # Open-Meteo has only ever served `/v1/` and does not document it as a version users can choose
    # between, so there is nothing meaningful to pin.
    api_docs_url = "https://open-meteo.com/en/docs"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPENMETEO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OPEN_METEO,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Open-Meteo",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["weather", "forecast", "climate", "air quality"],
            caption=CAPTION,
            iconPath="/static/services/open_meteo.png",
            docsUrl="https://open-meteo.com/en/docs",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="locations",
                        label="Locations",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="51.5074,-0.1278,London\n40.7128,-74.0060,New York",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Historical start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2024-01-01",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key (commercial plans only)",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.open_meteo.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Open-Meteo rejected the API key": "Open-Meteo rejected the API key. Check the key in your Open-Meteo customer account, then reconnect.",
            # A 4xx here means a parameter Open-Meteo will not accept (an out-of-range coordinate, a
            # start date before the archive begins). Retrying can never satisfy it.
            "Open-Meteo rejected the request": "Open-Meteo rejected the request. Check the locations and historical start date on this source, then reconnect.",
        }

    def get_schemas(
        self,
        config: OpenMeteoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint.name,
                supports_incremental=endpoint.supports_incremental,
                supports_append=endpoint.supports_append,
                incremental_fields=endpoint.incremental_fields,
                description=endpoint.description,
                default_incremental_lookback_seconds=endpoint.default_incremental_lookback_seconds,
                detected_primary_keys=endpoint.primary_keys,
            )
            for endpoint in (OPEN_METEO_ENDPOINTS[name] for name in ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: OpenMeteoSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_open_meteo_credentials(config.locations, config.api_key, config.start_date)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OpenMeteoResumeConfig]:
        # Endpoints store incompatible cursors (a date for the archive, a location index for the
        # rolling ones), so each keeps its resume state in its own namespace.
        return ResumableSourceManager[OpenMeteoResumeConfig](
            inputs, OpenMeteoResumeConfig, namespace=inputs.schema_name
        )

    def source_for_pipeline(
        self,
        config: OpenMeteoSourceConfig,
        resumable_source_manager: ResumableSourceManager[OpenMeteoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return open_meteo_source(
            endpoint_name=inputs.schema_name,
            locations_raw=config.locations,
            api_key=config.api_key,
            start_date_raw=config.start_date,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            resumable_source_manager=resumable_source_manager,
            logger=inputs.logger,
        )
