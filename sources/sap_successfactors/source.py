from typing import cast

from sources.sap_successfactors._config import SapSuccessFactorsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class SapSuccessFactorsSource(SimpleSource[SapSuccessFactorsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SAPSUCCESSFACTORS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SAPSUCCESSFACTORS,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="SAP SuccessFactors",
            iconPath="/static/services/sap_successfactors.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
