from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PrefectCloudSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PrefectCloudSource(SimpleSource[PrefectCloudSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PREFECTCLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PREFECT_CLOUD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Prefect (Prefect Technologies, Inc.)",
            iconPath="/static/services/prefect_cloud.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
