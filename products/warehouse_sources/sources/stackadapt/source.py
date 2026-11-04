from typing import cast

from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from products.warehouse_sources.sources.stackadapt._config import StackAdaptSourceConfig


@SourceRegistry.register
class StackAdaptSource(SimpleSource[StackAdaptSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STACKADAPT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.STACKADAPT,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="StackAdapt",
            iconPath="/static/services/stackadapt.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
