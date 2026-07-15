from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    Rapid7InsightvmSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class Rapid7InsightvmSource(SimpleSource[Rapid7InsightvmSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RAPID7INSIGHTVM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RAPID7_INSIGHTVM,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Rapid7 InsightVM",
            iconPath="/static/services/rapid7_insightvm.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
