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
from products.warehouse_sources.backend.temporal.data_imports.sources.breezometer.breezometer import (
    breezometer_source,
    validate_credentials as validate_breezometer_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.breezometer.settings import (
    BREEZOMETER_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BreezometerSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BreezometerSource(SimpleSource[BreezometerSourceConfig]):
    # `get_schemas` iterates a static endpoint catalog with no I/O, so the table list is safe to render
    # in public docs without credentials.
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BREEZOMETER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BREEZOMETER,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="BreezoMeter",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your API key and the locations you want to track to pull air-quality and pollen data into the PostHog Data warehouse.

BreezoMeter is now part of **Google Maps Platform** — this source uses the [Air Quality API](https://developers.google.com/maps/documentation/air-quality) and the [Pollen API](https://developers.google.com/maps/documentation/pollen). Create an API key in the [Google Cloud console](https://console.cloud.google.com/apis/credentials) and enable both APIs for your project.

There is no list endpoint — every request is for a single coordinate — so enter one location per line as `lat,lon` (an optional label is allowed: `lat,lon,label`). For example:

```
51.5074,-0.1278,London
40.7128,-74.0060,New York
```

Each sync polls every location once per table. To accumulate a history of point-in-time snapshots, pick the **append** sync method on the table.
""",
            iconPath="/static/services/breezometer.png",
            docsUrl="https://posthog.com/docs/cdp/sources/breezometer",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your Google Maps Platform API key",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.breezometer.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid key surfaces as a 400 (`API key not valid`) and a project without the API
            # enabled as a 403 (`PERMISSION_DENIED`), both via `raise_for_status()`. Retrying can never
            # satisfy a credential/enablement problem. Match the stable status text and base host (the
            # `key` query param is redacted before the message reaches here).
            "400 Client Error: Bad Request for url: https://airquality.googleapis.com": "Your API key is invalid, or the Air Quality API is not enabled for your Google Cloud project. Check the key and enable the API, then reconnect.",
            "403 Client Error: Forbidden for url: https://airquality.googleapis.com": "Your API key does not have access to the Air Quality API. Enable the API for your Google Cloud project and check any key restrictions, then reconnect.",
            "400 Client Error: Bad Request for url: https://pollen.googleapis.com": "Your API key is invalid, or the Pollen API is not enabled for your Google Cloud project. Check the key and enable the API, then reconnect.",
            "403 Client Error: Forbidden for url: https://pollen.googleapis.com": "Your API key does not have access to the Pollen API. Enable the API for your Google Cloud project and check any key restrictions, then reconnect.",
        }

    def get_schemas(
        self,
        config: BreezometerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # No endpoint exposes a server-side change cursor, so none is truly incremental.
                # Append is supported: each sync re-polls the snapshot and merge dedupes on
                # `[latitude, longitude, dt_iso]`, accumulating a time series across runs.
                supports_incremental=False,
                supports_append=True,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=BREEZOMETER_ENDPOINTS[endpoint].should_sync_default,
                description=BREEZOMETER_ENDPOINTS[endpoint].description,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: BreezometerSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_breezometer_credentials(config.api_key, config.locations)

    def source_for_pipeline(self, config: BreezometerSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return breezometer_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            locations_raw=config.locations,
            logger=inputs.logger,
        )
