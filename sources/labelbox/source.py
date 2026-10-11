from typing import cast

from sources.labelbox._config import LabelboxSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class LabelboxSource(SimpleSource[LabelboxSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LABELBOX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LABELBOX,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Labelbox",
            iconPath="/static/services/labelbox.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
