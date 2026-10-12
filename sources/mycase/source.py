from typing import cast

from sources.mycase._config import MycaseSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MycaseSource(SimpleSource[MycaseSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MYCASE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MYCASE,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="MyCase (AffiniPay)",
            iconPath="/static/services/mycase.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
