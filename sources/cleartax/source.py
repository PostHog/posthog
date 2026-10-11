from typing import cast

from sources.cleartax._config import CleartaxSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CleartaxSource(SimpleSource[CleartaxSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLEARTAX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CLEARTAX,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="ClearTax (Clear / Defmacro Software Pvt. Ltd.)",
            iconPath="/static/services/cleartax.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
