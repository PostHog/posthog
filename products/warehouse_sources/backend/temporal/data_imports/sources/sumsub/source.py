from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SumsubSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SumsubSource(SimpleSource[SumsubSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SUMSUB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SUMSUB,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Sumsub",
            iconPath="/static/services/sumsub.png",
            keywords=["kyc", "identity verification", "aml", "compliance"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
