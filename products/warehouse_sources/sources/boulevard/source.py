from typing import cast

from products.warehouse_sources.sources.boulevard._config import BoulevardSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class BoulevardSource(SimpleSource[BoulevardSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BOULEVARD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BOULEVARD,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Boulevard (joinblvd)",
            iconPath="/static/services/boulevard.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
