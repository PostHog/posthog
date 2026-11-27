from typing import cast

from products.warehouse_sources.sources.appdirect._config import AppdirectSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AppdirectSource(SimpleSource[AppdirectSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APPDIRECT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.APPDIRECT,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="AppDirect",
            iconPath="/static/services/appdirect.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
