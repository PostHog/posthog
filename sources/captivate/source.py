from typing import cast

from sources.captivate._config import CaptivateSourceConfig
from sources.sdk import (
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
