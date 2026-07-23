from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mezmo import MezmoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MezmoSource(SimpleSource[MezmoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MEZMO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MEZMO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Mezmo (formerly LogDNA)",
            iconPath="/static/services/mezmo.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
