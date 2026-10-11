from typing import cast

from sources.oracle_fusion._config import OracleFusionSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class OracleFusionSource(SimpleSource[OracleFusionSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ORACLEFUSION

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ORACLEFUSION,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            keywords=["oracle erp", "fusion"],
            label="Oracle Fusion",
            iconPath="/static/services/oracle.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
