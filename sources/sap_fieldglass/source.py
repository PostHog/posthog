from typing import cast

from sources.sap_fieldglass._config import SAPFieldglassSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class SAPFieldglassSource(SimpleSource[SAPFieldglassSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SAPFIELDGLASS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SAPFIELDGLASS,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="SAP Fieldglass",
            iconPath="/static/services/sap_fieldglass.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
