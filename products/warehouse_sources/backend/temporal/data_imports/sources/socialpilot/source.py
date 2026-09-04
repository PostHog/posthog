from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.socialpilot import (
    SocialPilotSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SocialPilotSource(SimpleSource[SocialPilotSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SOCIALPILOT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SOCIAL_PILOT,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="SocialPilot",
            keywords=["socialpilot.co"],
            iconPath="/static/services/socialpilot.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
