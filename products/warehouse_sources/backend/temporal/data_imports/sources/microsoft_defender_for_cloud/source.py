from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.microsoftdefenderforcloud import (
    MicrosoftDefenderForCloudSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MicrosoftDefenderForCloudSource(SimpleSource[MicrosoftDefenderForCloudSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTDEFENDERFORCLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MICROSOFTDEFENDERFORCLOUD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft (Defender for Cloud)",
            iconPath="/static/services/microsoft_defender_for_cloud.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
