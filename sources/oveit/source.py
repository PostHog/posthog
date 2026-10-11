from typing import cast

from sources.oveit._config import OveitSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class OveitSource(SimpleSource[OveitSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OVEIT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.OVEIT,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Oveit",
            iconPath="/static/services/oveit.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
