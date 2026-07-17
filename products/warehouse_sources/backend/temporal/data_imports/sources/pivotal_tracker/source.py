from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    PivotalTrackerSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PivotalTrackerSource(SimpleSource[PivotalTrackerSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PIVOTALTRACKER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PIVOTAL_TRACKER,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Pivotal Tracker",
            iconPath="/static/services/pivotal_tracker.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
