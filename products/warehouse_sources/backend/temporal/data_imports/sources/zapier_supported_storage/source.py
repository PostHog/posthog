from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    ZapierSupportedStorageSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ZapierSupportedStorageSource(SimpleSource[ZapierSupportedStorageSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZAPIERSUPPORTEDSTORAGE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZAPIER_SUPPORTED_STORAGE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Zapier Supported Storage",
            iconPath="/static/services/zapier_supported_storage.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
