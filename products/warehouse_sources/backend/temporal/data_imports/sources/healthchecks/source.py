from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HealthchecksSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HealthchecksSource(SimpleSource[HealthchecksSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HEALTHCHECKS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HEALTHCHECKS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            keywords=["healthchecks.io", "cron monitoring"],
            label="Healthchecks.io",
            iconPath="/static/services/healthchecks.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
