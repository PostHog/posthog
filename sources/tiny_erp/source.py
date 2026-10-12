from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.tiny_erp._config import TinyErpSourceConfig


@SourceRegistry.register
class TinyErpSource(SimpleSource[TinyErpSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TINYERP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TINYERP,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Olist Tiny ERP (API v3)",
            iconPath="/static/services/tiny_erp.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
