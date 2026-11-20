from typing import cast

from products.warehouse_sources.sources.captivate._config import CaptivateSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CaptivateSource(SimpleSource[CaptivateSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CAPTIVATE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CAPTIVATE,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Captivate (Captivate.fm)",
            iconPath="/static/services/captivate.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
