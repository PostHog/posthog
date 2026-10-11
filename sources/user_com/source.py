from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.user_com._config import UserComSourceConfig


@SourceRegistry.register
class UserComSource(SimpleSource[UserComSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.USERCOM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.USERCOM,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="User.com",
            iconPath="/static/services/user_com.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
