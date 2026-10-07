from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vimeo import VimeoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class VimeoSource(SimpleSource[VimeoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VIMEO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.VIMEO,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Vimeo",
            keywords=["video"],
            iconPath="/static/services/vimeo.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
