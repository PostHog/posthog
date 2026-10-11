from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.virtuous._config import VirtuousSourceConfig


@SourceRegistry.register
class VirtuousSource(SimpleSource[VirtuousSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VIRTUOUS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.VIRTUOUS,
            category=DataWarehouseSourceCategory.CRM,
            label="Virtuous (Virtuous Software / Virtuous CRM+)",
            iconPath="/static/services/virtuous.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
