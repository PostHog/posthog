from typing import cast

from sources.postnord._config import PostNordSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PostNordSource(SimpleSource[PostNordSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POSTNORD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.POSTNORD,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="PostNord",
            iconPath="/static/services/postnord.png",
            keywords=["shipping", "logistics", "parcel", "delivery"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
