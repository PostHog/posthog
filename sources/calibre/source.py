from typing import cast

from sources.calibre._config import CalibreSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CalibreSource(SimpleSource[CalibreSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CALIBRE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CALIBRE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Calibre (calibreapp.com)",
            iconPath="/static/services/calibre.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
