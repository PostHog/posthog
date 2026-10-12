from typing import cast

from sources.sap_concur._config import SapConcurSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class SapConcurSource(SimpleSource[SapConcurSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SAPCONCUR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SAPCONCUR,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="SAP Concur",
            iconPath="/static/services/sap_concur.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
