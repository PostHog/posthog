from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.socialpilot._config import SocialPilotSourceConfig


@SourceRegistry.register
class SocialPilotSource(SimpleSource[SocialPilotSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SOCIALPILOT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SOCIALPILOT,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="SocialPilot",
            keywords=["socialpilot.co"],
            iconPath="/static/services/socialpilot.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
