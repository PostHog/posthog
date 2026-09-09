from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.frappehelpdesk import (
    FrappeHelpdeskSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FrappeHelpdeskSource(SimpleSource[FrappeHelpdeskSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FRAPPEHELPDESK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FRAPPE_HELPDESK,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Frappe Helpdesk",
            iconPath="/static/services/frappe_helpdesk.png",
            keywords=["frappe", "erpnext", "helpdesk", "tickets"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
