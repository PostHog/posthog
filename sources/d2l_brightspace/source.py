from typing import cast

from sources.d2l_brightspace._config import D2lBrightspaceSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class D2lBrightspaceSource(SimpleSource[D2lBrightspaceSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.D2LBRIGHTSPACE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.D2LBRIGHTSPACE,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="D2L Brightspace",
            iconPath="/static/services/d2l_brightspace.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
