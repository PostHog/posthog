from typing import cast

from products.warehouse_sources.sources.akamai_reporting._config import AkamaiReportingSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AkamaiReportingSource(SimpleSource[AkamaiReportingSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AKAMAIREPORTING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AKAMAIREPORTING,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Akamai Technologies",
            iconPath="/static/services/akamai_reporting.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
