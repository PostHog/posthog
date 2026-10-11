from typing import cast

from sources.facebook_pages._config import FacebookPagesSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class FacebookPagesSource(SimpleSource[FacebookPagesSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FACEBOOKPAGES

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FACEBOOKPAGES,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Facebook Pages",
            iconPath="/static/services/facebook_pages.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
