from typing import cast

from products.warehouse_sources.sources.odoo._config import OdooSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class OdooSource(SimpleSource[OdooSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ODOO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ODOO,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            keywords=["erp", "crm"],
            label="Odoo",
            iconPath="/static/services/odoo.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
