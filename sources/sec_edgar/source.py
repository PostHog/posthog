from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.sec_edgar._config import SecEdgarSourceConfig


@SourceRegistry.register
class SecEdgarSource(SimpleSource[SecEdgarSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SECEDGAR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SECEDGAR,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="SEC EDGAR",
            iconPath="/static/services/sec_edgar.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
