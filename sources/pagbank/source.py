from typing import cast

from sources.pagbank._config import PagbankSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PagbankSource(SimpleSource[PagbankSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PAGBANK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PAGBANK,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="PagBank (PagSeguro), a PagSeguro Digital / UOL company",
            iconPath="/static/services/pagbank.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
