from typing import cast

from sources.commission_junction._config import CommissionJunctionSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CommissionJunctionSource(SimpleSource[CommissionJunctionSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COMMISSIONJUNCTION

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.COMMISSIONJUNCTION,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Commission Junction",
            iconPath="/static/services/commission_junction.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
