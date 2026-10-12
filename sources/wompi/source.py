from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.wompi._config import WompiSourceConfig


@SourceRegistry.register
class WompiSource(SimpleSource[WompiSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WOMPI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.WOMPI,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Wompi (Bancolombia)",
            iconPath="/static/services/wompi.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
