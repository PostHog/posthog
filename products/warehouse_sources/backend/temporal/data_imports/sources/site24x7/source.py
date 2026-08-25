from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.site24x7 import (
    Site24x7SourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class Site24x7Source(SimpleSource[Site24x7SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SITE24X7

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SITE24X7,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Site24x7 (Zoho Corporation)",
            iconPath="/static/services/site24x7.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
