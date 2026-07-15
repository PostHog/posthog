from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import QualysVmdrSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class QualysVmdrSource(SimpleSource[QualysVmdrSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.QUALYSVMDR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.QUALYS_VMDR,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Qualys, Inc. (Qualys VMDR)",
            iconPath="/static/services/qualys_vmdr.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
