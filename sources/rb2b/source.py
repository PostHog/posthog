from typing import cast

from sources.rb2b._config import RB2BSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class RB2BSource(SimpleSource[RB2BSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RB2B

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.RB2B,
            category=DataWarehouseSourceCategory.CRM,
            label="RB2B",
            iconPath="/static/services/rb2b.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
