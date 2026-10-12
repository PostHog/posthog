from typing import cast

from sources.sap_hana._config import SapHanaSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class SapHanaSource(SimpleSource[SapHanaSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SAPHANA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SAPHANA,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["sql"],
            label="SAP HANA",
            iconPath="/static/services/sap_hana.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
