from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CiscoDuoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CiscoDuoSource(SimpleSource[CiscoDuoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CISCODUO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CISCO_DUO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Cisco Duo (Duo Security)",
            iconPath="/static/services/cisco_duo.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
