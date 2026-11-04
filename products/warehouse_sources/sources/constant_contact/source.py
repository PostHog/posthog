from typing import cast

from products.warehouse_sources.sources.constant_contact._config import ConstantContactSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ConstantContactSource(SimpleSource[ConstantContactSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CONSTANTCONTACT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CONSTANTCONTACT,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Constant Contact",
            iconPath="/static/services/constant_contact.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
