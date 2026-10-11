from typing import cast

from sources.mirakl._config import MiraklSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MiraklSource(SimpleSource[MiraklSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MIRAKL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MIRAKL,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Mirakl (Mirakl Marketplace Platform Seller API)",
            iconPath="/static/services/mirakl.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
