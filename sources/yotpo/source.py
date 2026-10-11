from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.yotpo._config import YotpoSourceConfig


@SourceRegistry.register
class YotpoSource(SimpleSource[YotpoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.YOTPO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.YOTPO,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Yotpo",
            iconPath="/static/services/yotpo.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
