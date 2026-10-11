from typing import cast

from sources.paychex._config import PaychexSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PaychexSource(SimpleSource[PaychexSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PAYCHEX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PAYCHEX,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Paychex (Paychex Flex)",
            iconPath="/static/services/paychex.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
