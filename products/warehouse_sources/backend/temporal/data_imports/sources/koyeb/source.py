from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import KoyebSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KoyebSource(SimpleSource[KoyebSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KOYEB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KOYEB,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Koyeb",
            iconPath="/static/services/koyeb.png",
            keywords=["serverless", "deployments", "hosting", "infrastructure"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
