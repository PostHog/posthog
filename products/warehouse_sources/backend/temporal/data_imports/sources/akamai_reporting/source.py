from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.akamaireporting import (
    AkamaiReportingSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AkamaiReportingSource(SimpleSource[AkamaiReportingSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AKAMAIREPORTING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AKAMAI_REPORTING,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Akamai Technologies",
            iconPath="/static/services/akamai_reporting.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
