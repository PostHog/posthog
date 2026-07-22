from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.blackboardlearn import (
    BlackboardLearnSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BlackboardLearnSource(SimpleSource[BlackboardLearnSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BLACKBOARDLEARN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BLACKBOARD_LEARN,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Anthology Blackboard Learn",
            iconPath="/static/services/blackboard_learn.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
