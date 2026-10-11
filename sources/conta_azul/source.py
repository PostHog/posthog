from typing import cast

from sources.conta_azul._config import ContaAzulSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ContaAzulSource(SimpleSource[ContaAzulSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CONTAAZUL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CONTAAZUL,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Conta Azul",
            iconPath="/static/services/conta_azul.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
