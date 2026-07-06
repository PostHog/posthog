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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OpenWeatherSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.openweather.openweather import (
    openweather_source,
    validate_credentials as validate_openweather_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openweather.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    OPENWEATHER_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OpenWeatherSource(SimpleSource[OpenWeatherSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPENWEATHER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OPEN_WEATHER,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="OpenWeather",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your OpenWeather API key and the locations you want to track to pull weather data into the PostHog Data warehouse.

Create an API key in your [OpenWeather account](https://home.openweathermap.org/api_keys). A newly created key can take a couple of hours to activate.

OpenWeather has no list endpoint — every request is for a single coordinate — so enter one location per line as `lat,lon` (an optional label is allowed: `lat,lon,label`). For example:

```
51.5074,-0.1278,London
40.7128,-74.0060,New York
```

Each sync polls every location once. To accumulate a history of point-in-time snapshots, pick the **append** sync method on the table.
""",
            iconPath="/static/services/openweather.png",
            docsUrl="https://openweathermap.org/api",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your OpenWeather API key",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="locations",
                        label="Locations",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="51.5074,-0.1278,London\n40.7128,-74.0060,New York",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.openweather.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A missing/invalid key (or a key not subscribed to the requested product) surfaces as a
            # 401 when `_fetch` calls `raise_for_status()`. Retrying can never satisfy it.
            "401 Client Error: Unauthorized for url: https://api.openweathermap.org": "Your OpenWeather API key is invalid, not yet activated, or not subscribed to this product. Check the key in your OpenWeather account, then reconnect.",
        }

    def get_schemas(
        self,
        config: OpenWeatherSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # No server-side timestamp filter exists, so this is not true incremental sync.
                # Append is supported: each sync re-polls the (cheap) snapshot and merge dedupes on
                # `[lat, lon, dt]`, accumulating a time series across runs.
                supports_incremental=False,
                supports_append=True,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=OPENWEATHER_ENDPOINTS[endpoint].should_sync_default,
                description=OPENWEATHER_ENDPOINTS[endpoint].description,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: OpenWeatherSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_openweather_credentials(config.api_key, config.locations)

    def source_for_pipeline(self, config: OpenWeatherSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return openweather_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            locations_raw=config.locations,
            logger=inputs.logger,
        )
