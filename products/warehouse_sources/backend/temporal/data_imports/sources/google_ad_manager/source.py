from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    GoogleAdManagerSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GoogleAdManagerSource(SimpleSource[GoogleAdManagerSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEADMANAGER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_AD_MANAGER,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["gam"],
            label="Google Ad Manager",
            iconPath="/static/services/google_ad_manager.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
