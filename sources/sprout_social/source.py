from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.sprout_social._config import SproutSocialSourceConfig


@SourceRegistry.register
class SproutSocialSource(SimpleSource[SproutSocialSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SPROUTSOCIAL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SPROUTSOCIAL,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Sprout Social",
            iconPath="/static/services/sprout_social.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
