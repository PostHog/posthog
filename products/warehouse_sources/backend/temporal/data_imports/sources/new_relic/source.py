from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import NewRelicSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NewRelicSource(SimpleSource[NewRelicSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NEWRELIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.NEW_RELIC,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            keywords=["new relic", "apm", "observability"],
            label="New Relic",
            iconPath="/static/services/new_relic.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
