from typing import cast

from sources.crisp._config import CrispSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CrispSource(SimpleSource[CrispSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CRISP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CRISP,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Crisp",
            iconPath="/static/services/crisp.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
