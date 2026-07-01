from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HelpScoutSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HelpScoutSource(SimpleSource[HelpScoutSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HELPSCOUT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HELP_SCOUT,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            keywords=["helpscout"],
            label="Help Scout",
            iconPath="/static/services/helpscout.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
