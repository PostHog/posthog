from typing import cast

from sources.imf_data._config import ImfDataSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ImfDataSource(SimpleSource[ImfDataSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.IMFDATA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.IMFDATA,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="IMF Data (International Monetary Fund SDMX API)",
            iconPath="/static/services/imf_data.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
