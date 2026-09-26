from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.electricity_maps.electricity_maps import (
    ElectricityMapsResumeConfig,
    electricity_maps_source,
    invalid_zones,
    parse_zones,
    validate_credentials as validate_electricity_maps_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.electricity_maps.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.electricitymaps import (
    ElectricityMapsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ElectricityMapsSource(ResumableSource[ElectricityMapsSourceConfig, ElectricityMapsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://app.electricitymaps.com/docs/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ELECTRICITYMAPS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Electricity Maps rejected your API token. Check the token in the Electricity Maps portal and reconnect the source.",
            "403 Client Error": "Your Electricity Maps token does not have access to a configured zone or the requested history range. Check your plan in the Electricity Maps portal.",
            "404 Client Error": "Electricity Maps does not recognize one of the configured zones. Check the zone identifiers in the source settings.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.electricity_maps.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ElectricityMapsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: ElectricityMapsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        zones = parse_zones(config.zones)
        if not zones:
            return False, "Enter at least one zone identifier, like DE or DK-DK1."

        malformed = invalid_zones(zones)
        if malformed:
            return (
                False,
                f"These don't look like zone identifiers: {', '.join(malformed)}. "
                "Enter comma-separated zone codes, like DE, DK-DK1, US-CAL-CISO.",
            )

        return validate_electricity_maps_credentials(config.api_token, zones)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ElectricityMapsResumeConfig]:
        return ResumableSourceManager[ElectricityMapsResumeConfig](inputs, ElectricityMapsResumeConfig)

    def source_for_pipeline(
        self,
        config: ElectricityMapsSourceConfig,
        resumable_source_manager: ResumableSourceManager[ElectricityMapsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return electricity_maps_source(
            api_token=config.api_token,
            zones=parse_zones(config.zones),
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            history_days=config.history_days,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ELECTRICITYMAPS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Electricity Maps",
            caption="Enter your Electricity Maps API token, created in the "
            "[Electricity Maps portal](https://portal.electricitymaps.com/).\n\n"
            "Zones is a comma-separated list of zone identifiers to sync, like `DE, DK-DK1, US-CAL-CISO`. "
            "Zone access and history depth depend on your Electricity Maps plan.",
            keywords=["carbon intensity", "grid", "electricity map"],
            docsUrl="https://posthog.com/docs/cdp/sources/electricity-maps",
            iconPath="/static/services/electricity_maps.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="zones",
                        label="Zones",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="DE, DK-DK1, US-CAL-CISO",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="history_days",
                        label="Days of history to sync initially",
                        type=SourceFieldInputConfigType.NUMBER,
                        required=False,
                        placeholder="30",
                        secret=False,
                    ),
                ],
            ),
        )
