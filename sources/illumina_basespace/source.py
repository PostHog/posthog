from typing import cast

from sources.illumina_basespace._config import IlluminaBasespaceSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class IlluminaBasespaceSource(SimpleSource[IlluminaBasespaceSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ILLUMINABASESPACE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ILLUMINABASESPACE,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Illumina Basespace",
            iconPath="/static/services/illumina_basespace.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
