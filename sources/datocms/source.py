from typing import cast

from sources.datocms._config import DatoCMSSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DatoCMSSource(SimpleSource[DatoCMSSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DATOCMS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DATOCMS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="DatoCMS",
            iconPath="/static/services/datocms.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
