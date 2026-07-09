from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    AikidoSecuritySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AikidoSecuritySource(SimpleSource[AikidoSecuritySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AIKIDOSECURITY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AIKIDO_SECURITY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Aikido Security",
            iconPath="/static/services/aikido_security.png",
            keywords=["security", "devsecops", "vulnerabilities", "appsec"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
