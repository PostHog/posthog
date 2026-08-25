from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pagbank import (
    PagbankSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PagbankSource(SimpleSource[PagbankSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PAGBANK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PAGBANK,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="PagBank (PagSeguro), a PagSeguro Digital / UOL company",
            iconPath="/static/services/pagbank.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
