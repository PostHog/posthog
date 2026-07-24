from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.noaacdo import (
    NoaaCdoSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NoaaCdoSource(SimpleSource[NoaaCdoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NOAACDO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.NOAA_CDO,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="NOAA Climate Data Online (NCEI)",
            iconPath="/static/services/noaa_cdo.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
