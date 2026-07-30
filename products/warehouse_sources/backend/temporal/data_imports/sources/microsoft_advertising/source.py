from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.microsoftadvertising import (
    MicrosoftAdvertisingSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MicrosoftAdvertisingSource(SimpleSource[MicrosoftAdvertisingSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTADVERTISING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MICROSOFT_ADVERTISING,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Microsoft Advertising (Bing Ads)",
            iconPath="/static/services/microsoft_advertising.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
