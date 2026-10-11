from typing import cast

from sources.encharge._config import EnchargeSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class EnchargeSource(SimpleSource[EnchargeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ENCHARGE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ENCHARGE,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Encharge",
            iconPath="/static/services/encharge.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
