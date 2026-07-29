from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pluralsightflow import (
    PluralsightFlowSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PluralsightFlowSource(SimpleSource[PluralsightFlowSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PLURALSIGHTFLOW

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PLURALSIGHT_FLOW,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Pluralsight Flow",
            iconPath="/static/services/pluralsight_flow.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
