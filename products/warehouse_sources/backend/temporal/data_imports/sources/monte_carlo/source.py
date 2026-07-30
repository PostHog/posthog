from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MonteCarloSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MonteCarloSource(SimpleSource[MonteCarloSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MONTECARLO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MONTE_CARLO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Monte Carlo Data, Inc.",
            iconPath="/static/services/monte_carlo.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
