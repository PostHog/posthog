from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.userback._config import UserbackSourceConfig


@SourceRegistry.register
class UserbackSource(SimpleSource[UserbackSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.USERBACK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.USERBACK,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Userback",
            iconPath="/static/services/userback.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
