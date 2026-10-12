from typing import cast

from sources.oneleet._config import OneleetSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class OneleetSource(SimpleSource[OneleetSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ONELEET

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ONELEET,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Oneleet",
            iconPath="/static/services/oneleet.png",
            keywords=["compliance", "grc", "soc2", "security"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
