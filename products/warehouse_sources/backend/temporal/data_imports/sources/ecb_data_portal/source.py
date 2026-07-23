from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ecbdataportal import (
    EcbDataPortalSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class EcbDataPortalSource(SimpleSource[EcbDataPortalSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ECBDATAPORTAL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ECB_DATA_PORTAL,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="European Central Bank (ECB Data Portal)",
            iconPath="/static/services/ecb_data_portal.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
