from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.oneleet import (
    OneleetSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OneleetSource(SimpleSource[OneleetSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ONELEET

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ONELEET,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Oneleet",
            iconPath="/static/services/oneleet.png",
            keywords=["compliance", "grc", "soc2", "security"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
