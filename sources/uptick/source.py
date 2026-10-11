from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.uptick._config import UptickSourceConfig


@SourceRegistry.register
class UptickSource(SimpleSource[UptickSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.UPTICK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.UPTICK,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Uptick",
            iconPath="/static/services/uptick.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
