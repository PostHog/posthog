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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ShipStationSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.shipstation import (
    ShipStationResumeConfig,
    shipstation_source,
    validate_credentials as validate_shipstation_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ShipStationSource(ResumableSource[ShipStationSourceConfig, ShipStationResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SHIPSTATION

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://ssapi.shipstation.com": "ShipStation authentication failed. Please check your API key and API secret.",
            "403 Client Error: Forbidden for url: https://ssapi.shipstation.com": "ShipStation denied access. Please check that your plan includes API access.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SHIP_STATION,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="ShipStation",
            caption="""Enter your ShipStation API credentials to pull your ShipStation order and shipping data into the PostHog Data warehouse.

You can find your API key and API secret in [ShipStation](https://ship.shipstation.com/settings/api-settings) under Settings > Account > API Settings. API access requires a ShipStation plan tier that includes it.""",
            iconPath="/static/services/shipstation.png",
            docsUrl="https://posthog.com/docs/cdp/sources/shipstation",
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
                        name="api_secret",
                        label="API secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: ShipStationSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: ShipStationSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_shipstation_credentials(config.api_key, config.api_secret):
            return True, None

        return False, "Invalid ShipStation API credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ShipStationResumeConfig]:
        return ResumableSourceManager[ShipStationResumeConfig](inputs, ShipStationResumeConfig)

    def source_for_pipeline(
        self,
        config: ShipStationSourceConfig,
        resumable_source_manager: ResumableSourceManager[ShipStationResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return shipstation_source(
            api_key=config.api_key,
            api_secret=config.api_secret,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
