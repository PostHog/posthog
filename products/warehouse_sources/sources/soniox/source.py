from typing import cast

from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from products.warehouse_sources.sources.soniox._config import SonioxSourceConfig


@SourceRegistry.register
class SonioxSource(SimpleSource[SonioxSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SONIOX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SONIOX,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Soniox",
            iconPath="/static/services/soniox.png",
            keywords=["speech-to-text", "transcription"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
