from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    IlluminaBasespaceSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class IlluminaBasespaceSource(SimpleSource[IlluminaBasespaceSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ILLUMINABASESPACE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ILLUMINA_BASESPACE,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Illumina Basespace",
            iconPath="/static/services/illumina_basespace.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
