from typing import cast

from products.warehouse_sources.sources.athenahealth._config import AthenahealthSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AthenahealthSource(SimpleSource[AthenahealthSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ATHENAHEALTH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ATHENAHEALTH,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="athenahealth (athenaOne)",
            iconPath="/static/services/athenahealth.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
