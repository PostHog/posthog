from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sageaccounting import (
    SageAccountingSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SageAccountingSource(SimpleSource[SageAccountingSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SAGEACCOUNTING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SAGE_ACCOUNTING,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Sage Accounting",
            iconPath="/static/services/sage_accounting.png",
            keywords=["sage", "sage business cloud", "bookkeeping"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
