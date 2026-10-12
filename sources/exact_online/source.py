from typing import cast

from sources.exact_online._config import ExactOnlineSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ExactOnlineSource(SimpleSource[ExactOnlineSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EXACTONLINE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.EXACTONLINE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Exact Online",
            iconPath="/static/services/exact_online.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
