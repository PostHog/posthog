from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.hootsuite._config import HootsuiteSourceConfig


@SourceRegistry.register
class HootsuiteSource(SimpleSource[HootsuiteSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HOOTSUITE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.HOOTSUITE,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Hootsuite",
            iconPath="/static/services/hootsuite.png",
            keywords=["social media", "social media management", "scheduling"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
