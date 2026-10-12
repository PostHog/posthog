from typing import cast

from sources.microsoft_excel._config import MicrosoftExcelSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MicrosoftExcelSource(SimpleSource[MicrosoftExcelSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTEXCEL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MICROSOFTEXCEL,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            keywords=["excel", "spreadsheet", "xlsx"],
            label="Microsoft Excel",
            iconPath="/static/services/microsoft_excel.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
