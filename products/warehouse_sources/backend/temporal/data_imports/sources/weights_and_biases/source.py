from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    WeightsAndBiasesSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WeightsAndBiasesSource(SimpleSource[WeightsAndBiasesSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WEIGHTSANDBIASES

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WEIGHTS_AND_BIASES,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Weights & Biases",
            iconPath="/static/services/weights_and_biases.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
