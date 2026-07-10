from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PlatformShSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PlatformShSource(SimpleSource[PlatformShSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PLATFORMSH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PLATFORM_SH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Platform.sh",
            iconPath="/static/services/platform_sh.png",
            keywords=["paas", "deployments", "hosting", "devops"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
