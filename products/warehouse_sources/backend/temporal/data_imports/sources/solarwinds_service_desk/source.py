from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    SolarwindsServiceDeskSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SolarwindsServiceDeskSource(SimpleSource[SolarwindsServiceDeskSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SOLARWINDSSERVICEDESK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SOLARWINDS_SERVICE_DESK,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Solarwinds Service Desk",
            iconPath="/static/services/solarwinds_service_desk.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
