from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import Dynamics365SourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class Dynamics365Source(SimpleSource[Dynamics365SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DYNAMICS365

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DYNAMICS365,
            category=DataWarehouseSourceCategory.CRM,
            keywords=["microsoft dynamics", "dynamics"],
            label="Microsoft Dynamics 365",
            iconPath="/static/services/dynamics365.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
