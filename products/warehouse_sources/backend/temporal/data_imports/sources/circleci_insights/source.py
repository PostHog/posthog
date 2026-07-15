from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    CircleciInsightsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CircleciInsightsSource(SimpleSource[CircleciInsightsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CIRCLECIINSIGHTS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CIRCLECI_INSIGHTS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="CircleCI",
            iconPath="/static/services/circleci_insights.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
