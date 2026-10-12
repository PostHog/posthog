from typing import cast

from sources.infor_nexus._config import InforNexusSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class InforNexusSource(SimpleSource[InforNexusSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INFORNEXUS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.INFORNEXUS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Infor Nexus",
            iconPath="/static/services/infor_nexus.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
