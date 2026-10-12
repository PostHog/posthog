from typing import cast

from sources.emarsys._config import EmarsysSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class EmarsysSource(SimpleSource[EmarsysSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EMARSYS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.EMARSYS,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="SAP Emarsys",
            iconPath="/static/services/emarsys.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
