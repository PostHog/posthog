from typing import cast

from sources.lawmatics._config import LawmaticsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class LawmaticsSource(SimpleSource[LawmaticsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LAWMATICS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LAWMATICS,
            category=DataWarehouseSourceCategory.CRM,
            label="Lawmatics",
            iconPath="/static/services/lawmatics.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
