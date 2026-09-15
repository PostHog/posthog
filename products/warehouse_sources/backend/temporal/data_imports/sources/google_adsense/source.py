from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googleadsense import (
    GoogleAdSenseSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GoogleAdSenseSource(SimpleSource[GoogleAdSenseSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEADSENSE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLEADSENSE,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Google AdSense",
            iconPath="/static/services/google_adsense.png",
            keywords=["adsense", "ads"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
