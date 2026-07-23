from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.stackoverflowforteams import (
    StackOverflowForTeamsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class StackOverflowForTeamsSource(SimpleSource[StackOverflowForTeamsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STACKOVERFLOWFORTEAMS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.STACK_OVERFLOW_FOR_TEAMS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Stack Overflow (Prosus/Stack Exchange)",
            iconPath="/static/services/stack_overflow_for_teams.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
