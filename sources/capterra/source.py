from typing import cast

from sources.capterra._config import CapterraSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CapterraSource(SimpleSource[CapterraSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CAPTERRA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CAPTERRA,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Capterra",
            iconPath="/static/services/capterra.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
