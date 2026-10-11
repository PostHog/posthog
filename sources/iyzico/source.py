from typing import cast

from sources.iyzico._config import IyzicoSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class IyzicoSource(SimpleSource[IyzicoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.IYZICO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.IYZICO,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="iyzico (PayU group)",
            iconPath="/static/services/iyzico.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
