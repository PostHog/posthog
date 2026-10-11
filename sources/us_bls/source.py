from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.us_bls._config import UsBlsSourceConfig


@SourceRegistry.register
class UsBlsSource(SimpleSource[UsBlsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.USBLS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.USBLS,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="US Bureau of Labor Statistics (BLS) Public Data API",
            iconPath="/static/services/us_bls.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
