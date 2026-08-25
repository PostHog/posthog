from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.twoc2p import TwoC2pSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TwoC2pSource(SimpleSource[TwoC2pSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TWOC2P

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TWO_C2P,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="2C2P (One Stop Payment Services)",
            iconPath="/static/services/two_c2p.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
