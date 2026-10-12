from typing import cast

from sources.neon_crm._config import NeonCrmSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class NeonCrmSource(SimpleSource[NeonCrmSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NEONCRM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NEONCRM,
            category=DataWarehouseSourceCategory.CRM,
            label="Neon One (Neon CRM)",
            iconPath="/static/services/neon_crm.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
