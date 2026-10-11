from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.tebra._config import TebraSourceConfig


@SourceRegistry.register
class TebraSource(SimpleSource[TebraSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TEBRA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TEBRA,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Tebra (formerly Kareo)",
            iconPath="/static/services/tebra.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
