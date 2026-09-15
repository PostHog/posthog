from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.microsoftentraid import (
    MicrosoftEntraIdSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MicrosoftEntraIdSource(SimpleSource[MicrosoftEntraIdSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTENTRAID

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MICROSOFTENTRAID,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Entra Id",
            iconPath="/static/services/microsoft_entra_id.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
