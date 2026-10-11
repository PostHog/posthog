from typing import cast

from sources.hivebrite._config import HivebriteSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class HivebriteSource(SimpleSource[HivebriteSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HIVEBRITE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.HIVEBRITE,
            category=DataWarehouseSourceCategory.CRM,
            label="Hivebrite",
            iconPath="/static/services/hivebrite.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
