from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    AdpWorkforceNowSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AdpWorkforceNowSource(SimpleSource[AdpWorkforceNowSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ADPWORKFORCENOW

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ADP_WORKFORCE_NOW,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            keywords=["adp"],
            label="ADP Workforce Now",
            iconPath="/static/services/adp_workforce_now.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
