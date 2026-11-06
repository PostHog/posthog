from typing import cast

from products.warehouse_sources.sources.checkhq._config import CheckHQSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CheckHQSource(SimpleSource[CheckHQSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CHECKHQ

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CHECKHQ,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            keywords=["checkhq", "payroll"],
            label="Check",
            iconPath="/static/services/checkhq.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
