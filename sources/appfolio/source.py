from typing import cast

from sources.appfolio._config import AppfolioSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AppfolioSource(SimpleSource[AppfolioSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APPFOLIO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.APPFOLIO,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="AppFolio Property Manager",
            iconPath="/static/services/appfolio.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
