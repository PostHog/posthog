from typing import cast

from sources.pax8._config import Pax8SourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class Pax8Source(SimpleSource[Pax8SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PAX8

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PAX8,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Pax8",
            iconPath="/static/services/pax8.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
