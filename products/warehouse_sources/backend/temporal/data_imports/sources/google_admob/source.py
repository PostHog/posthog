from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googleadmob import (
    GoogleAdMobSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GoogleAdMobSource(SimpleSource[GoogleAdMobSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEADMOB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLEADMOB,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Google AdMob",
            iconPath="/static/services/google_admob.png",
            keywords=["admob", "ads"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
