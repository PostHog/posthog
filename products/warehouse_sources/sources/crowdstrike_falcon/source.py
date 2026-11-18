from typing import cast

from products.warehouse_sources.sources.crowdstrike_falcon._config import CrowdstrikeFalconSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CrowdstrikeFalconSource(SimpleSource[CrowdstrikeFalconSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CROWDSTRIKEFALCON

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CROWDSTRIKEFALCON,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="CrowdStrike",
            iconPath="/static/services/crowdstrike_falcon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
