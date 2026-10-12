from typing import cast

from sources.metriport._config import MetriportSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MetriportSource(SimpleSource[MetriportSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.METRIPORT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.METRIPORT,
            category=DataWarehouseSourceCategory.CRM,
            label="Metriport",
            iconPath="/static/services/metriport.png",
            keywords=["healthcare", "medical", "fhir", "patients"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
