from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.teamupfitness import (
    TeamupFitnessSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TeamupFitnessSource(SimpleSource[TeamupFitnessSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TEAMUPFITNESS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TEAMUP_FITNESS,
            category=DataWarehouseSourceCategory.CRM,
            label="TeamUp (goteamup.com, a DaySmart company)",
            iconPath="/static/services/teamup_fitness.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
