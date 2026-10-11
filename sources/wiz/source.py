from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.wiz._config import WizSourceConfig


@SourceRegistry.register
class WizSource(SimpleSource[WizSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WIZ

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.WIZ,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Wiz, Inc.",
            iconPath="/static/services/wiz.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
