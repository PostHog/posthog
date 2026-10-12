from typing import cast

from sources.sap_erp._config import SapErpSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class SapErpSource(SimpleSource[SapErpSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SAPERP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SAPERP,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="SAP ERP",
            iconPath="/static/services/sap_erp.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
