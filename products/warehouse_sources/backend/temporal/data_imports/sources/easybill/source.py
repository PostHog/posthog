from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.easybill import (
    EasybillSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class EasybillSource(SimpleSource[EasybillSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EASYBILL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.EASYBILL,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="easybill",
            iconPath="/static/services/easybill.png",
            keywords=["invoicing", "billing", "accounting"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
