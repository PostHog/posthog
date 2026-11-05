from typing import cast

from products.warehouse_sources.sources.onelogin._config import OneloginSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class OneloginSource(SimpleSource[OneloginSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ONELOGIN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ONELOGIN,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="OneLogin (One Identity / Quest Software)",
            iconPath="/static/services/onelogin.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
