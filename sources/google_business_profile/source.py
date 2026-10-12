from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.google_business_profile._config import GoogleBusinessProfileSourceConfig


@SourceRegistry.register
class GoogleBusinessProfileSource(SimpleSource[GoogleBusinessProfileSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEBUSINESSPROFILE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLEBUSINESSPROFILE,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Google Business Profile",
            keywords=["google my business", "gmb"],
            iconPath="/static/services/google_business_profile.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
