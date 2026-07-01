from typing import Optional, cast

import structlog

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

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cimis.cimis import (
    cimis_source,
    parse_targets,
    validate_credentials as validate_cimis_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cimis.settings import (
    CIMIS_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CimisSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CimisSource(SimpleSource[CimisSourceConfig]):
    # get_schemas iterates a static endpoint catalog with no I/O, so the table list is safe to surface
    # in public docs without credentials.
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CIMIS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CIMIS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="CIMIS",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Pull California weather and reference evapotranspiration (ETo) data from the [California Irrigation Management Information System (CIMIS)](https://cimis.water.ca.gov/) into the PostHog Data warehouse.

CIMIS is a free service. Register for a free account and create a **web-services appKey** in your [CIMIS account](https://et.water.ca.gov/Account/Login), then paste it below.

To sync the **daily** and **hourly** weather tables, set **Targets** to a comma-separated list of CIMIS station numbers (e.g. `2,8,127`). You can look up station numbers in the `stations` table or on the [CIMIS station map](https://cimis.water.ca.gov/Stations.aspx). The station and zip-code metadata tables sync without targets.""",
            iconPath="/static/services/cimis.png",
            docsUrl="https://posthog.com/docs/cdp/sources/cimis",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="app_key",
                        label="App key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="your CIMIS web-services appKey",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="targets",
                        label="Targets (station numbers)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2,8,127",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="unit_of_measure",
                        label="Unit of measure",
                        required=False,
                        defaultValue="E",
                        options=[
                            SourceFieldSelectConfigOption(label="English (°F, inches)", value="E"),
                            SourceFieldSelectConfigOption(label="Metric (°C, mm)", value="M"),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.cimis.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Matches the sanitized CimisHTTPError message (status code only) so the appKey embedded in the
        # request URL never reaches the matcher, logs, or error tracking.
        return {
            "CIMIS API error: status=401": "Your CIMIS appKey is invalid or has expired. Create a new appKey in your CIMIS account, then reconnect.",
            "CIMIS API error: status=403": "Your CIMIS appKey is invalid or has not been activated. Check the key in your CIMIS account, then reconnect.",
        }

    def get_schemas(
        self,
        config: CimisSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = CIMIS_ENDPOINTS[endpoint]
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: CimisSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        logger = structlog.get_logger(__name__)
        return validate_cimis_credentials(config.app_key, parse_targets(config.targets), logger)

    def source_for_pipeline(self, config: CimisSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return cimis_source(
            endpoint=inputs.schema_name,
            app_key=config.app_key,
            targets=parse_targets(config.targets),
            unit_of_measure=config.unit_of_measure or "E",
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
