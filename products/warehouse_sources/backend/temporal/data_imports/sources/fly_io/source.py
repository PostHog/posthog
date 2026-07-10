from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FlyIoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FlyIoSource(SimpleSource[FlyIoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FLYIO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FLY_IO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Fly.io",
            iconPath="/static/services/fly_io.png",
            keywords=["fly", "machines", "infrastructure", "cloud"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
