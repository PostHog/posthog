from typing import cast

from sources.raisely._config import RaiselySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class RaiselySource(SimpleSource[RaiselySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RAISELY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.RAISELY,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Raisely",
            iconPath="/static/services/raisely.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
