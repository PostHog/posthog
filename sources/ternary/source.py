from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.ternary._config import TernarySourceConfig


@SourceRegistry.register
class TernarySource(SimpleSource[TernarySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TERNARY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TERNARY,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Ternary",
            iconPath="/static/services/ternary.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
