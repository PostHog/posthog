from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.microsoftdataverse import (
    MicrosoftDataverseSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MicrosoftDataverseSource(SimpleSource[MicrosoftDataverseSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTDATAVERSE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MICROSOFTDATAVERSE,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Microsoft Dataverse",
            iconPath="/static/services/microsoft_dataverse.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
