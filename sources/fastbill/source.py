from typing import cast

from sources.fastbill._config import FastbillSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class FastbillSource(SimpleSource[FastbillSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FASTBILL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FASTBILL,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Fastbill",
            iconPath="/static/services/fastbill.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
