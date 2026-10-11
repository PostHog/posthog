from typing import cast

from sources.akeneo._config import AkeneoSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AkeneoSource(SimpleSource[AkeneoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AKENEO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AKENEO,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Akeneo",
            iconPath="/static/services/akeneo.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
