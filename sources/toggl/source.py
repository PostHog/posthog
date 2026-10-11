from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.toggl._config import TogglSourceConfig


@SourceRegistry.register
class TogglSource(SimpleSource[TogglSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TOGGL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TOGGL,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Toggl",
            iconPath="/static/services/toggl.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
