from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.crowdstrikefalcon import (
    CrowdstrikeFalconSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CrowdstrikeFalconSource(SimpleSource[CrowdstrikeFalconSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CROWDSTRIKEFALCON

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CROWDSTRIKE_FALCON,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="CrowdStrike",
            iconPath="/static/services/crowdstrike_falcon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
