from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.zellify._config import ZellifySourceConfig


@SourceRegistry.register
class ZellifySource(SimpleSource[ZellifySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZELLIFY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ZELLIFY,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Zellify",
            iconPath="/static/services/zellify.png",
            keywords=["web2app", "attribution", "funnels"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
