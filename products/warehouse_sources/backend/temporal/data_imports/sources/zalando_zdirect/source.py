from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zalandozdirect import (
    ZalandoZdirectSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ZalandoZdirectSource(SimpleSource[ZalandoZdirectSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZALANDOZDIRECT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZALANDO_ZDIRECT,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Zalando SE (zDirect Partner API)",
            iconPath="/static/services/zalando_zdirect.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
