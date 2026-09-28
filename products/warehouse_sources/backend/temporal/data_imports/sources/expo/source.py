from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.expo import ExpoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ExpoSource(SimpleSource[ExpoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EXPO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.EXPO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Expo",
            iconPath="/static/services/expo.png",
            keywords=["eas", "react native", "mobile"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
