from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.microsoftsentinel import (
    MicrosoftSentinelSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MicrosoftSentinelSource(SimpleSource[MicrosoftSentinelSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTSENTINEL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MICROSOFT_SENTINEL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Sentinel (Azure Security Insights)",
            iconPath="/static/services/microsoft_sentinel.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
