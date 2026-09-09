from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.frappecrm import (
    FrappeCRMSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FrappeCRMSource(SimpleSource[FrappeCRMSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FRAPPECRM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FRAPPE_CRM,
            category=DataWarehouseSourceCategory.CRM,
            label="Frappe CRM",
            iconPath="/static/services/frappe_crm.png",
            keywords=["frappe", "erpnext", "crm"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
