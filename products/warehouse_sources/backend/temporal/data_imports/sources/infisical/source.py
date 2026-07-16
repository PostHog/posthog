from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import InfisicalSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class InfisicalSource(SimpleSource[InfisicalSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INFISICAL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INFISICAL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Infisical",
            iconPath="/static/services/infisical.png",
            keywords=["secrets", "security", "audit", "devops"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
