from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import M3terSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class M3terSource(SimpleSource[M3terSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.M3TER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.M3TER,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="m3ter",
            iconPath="/static/services/m3ter.png",
            keywords=["billing", "usage-based billing", "metering", "invoicing"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
