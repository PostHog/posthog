from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.uk_ons._config import UkOnsSourceConfig


@SourceRegistry.register
class UkOnsSource(SimpleSource[UkOnsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.UKONS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.UKONS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="UK Office for National Statistics (ONS)",
            iconPath="/static/services/uk_ons.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
