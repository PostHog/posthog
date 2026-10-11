from typing import cast

from sources.fortnox._config import FortnoxSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class FortnoxSource(SimpleSource[FortnoxSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FORTNOX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FORTNOX,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Fortnox AB",
            iconPath="/static/services/fortnox.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
