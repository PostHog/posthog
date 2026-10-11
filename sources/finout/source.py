from typing import cast

from sources.finout._config import FinoutSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class FinoutSource(SimpleSource[FinoutSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FINOUT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FINOUT,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Finout",
            iconPath="/static/services/finout.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
