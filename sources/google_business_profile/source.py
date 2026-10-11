from typing import cast

from sources.google_business_profile._config import GoogleBusinessProfileSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


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
