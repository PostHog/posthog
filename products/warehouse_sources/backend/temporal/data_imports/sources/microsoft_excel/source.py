from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.microsoftexcel import (
    MicrosoftExcelSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MicrosoftExcelSource(SimpleSource[MicrosoftExcelSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTEXCEL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MICROSOFT_EXCEL,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            keywords=["excel", "spreadsheet", "xlsx"],
            label="Microsoft Excel",
            iconPath="/static/services/microsoft_excel.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
