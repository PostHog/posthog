from typing import cast

from sources.google_forms._config import GoogleFormsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GoogleFormsSource(SimpleSource[GoogleFormsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEFORMS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLEFORMS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Google Forms",
            iconPath="/static/services/google_forms.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
