from typing import cast

from sources.m3ter._config import M3terSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class M3terSource(SimpleSource[M3terSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.M3TER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.M3TER,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="m3ter",
            iconPath="/static/services/m3ter.com.png",
            keywords=["billing", "usage-based billing", "metering", "invoicing"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
