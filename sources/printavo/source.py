from typing import cast

from sources.printavo._config import PrintavoSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PrintavoSource(SimpleSource[PrintavoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PRINTAVO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PRINTAVO,
            category=DataWarehouseSourceCategory.CRM,
            label="Printavo",
            iconPath="/static/services/printavo.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
