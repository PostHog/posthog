from typing import cast

from sources.rent_manager._config import RentManagerSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class RentManagerSource(SimpleSource[RentManagerSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RENTMANAGER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.RENTMANAGER,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Rent Manager (London Computer Systems)",
            iconPath="/static/services/rent_manager.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
