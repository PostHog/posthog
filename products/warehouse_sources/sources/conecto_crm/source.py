from typing import cast

from products.warehouse_sources.sources.conecto_crm._config import ConectoCRMSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ConectoCRMSource(SimpleSource[ConectoCRMSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CONECTOCRM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CONECTOCRM,
            category=DataWarehouseSourceCategory.CRM,
            label="Conecto CRM",
            iconPath="/static/services/conecto_crm.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
