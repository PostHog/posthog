from typing import cast

from sources.redis._config import RedisSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class RedisSource(SimpleSource[RedisSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REDIS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.REDIS,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Redis",
            iconPath="/static/services/redis.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
