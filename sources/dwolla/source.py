from typing import cast

from sources.dwolla._config import DwollaSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DwollaSource(SimpleSource[DwollaSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DWOLLA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DWOLLA,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Dwolla",
            iconPath="/static/services/dwolla.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
