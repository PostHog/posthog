from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.zluri._config import ZluriSourceConfig


@SourceRegistry.register
class ZluriSource(SimpleSource[ZluriSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZLURI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ZLURI,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Zluri",
            iconPath="/static/services/zluri.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
