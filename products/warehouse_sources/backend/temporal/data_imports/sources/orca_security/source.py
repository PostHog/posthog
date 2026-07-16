from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OrcaSecuritySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OrcaSecuritySource(SimpleSource[OrcaSecuritySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ORCASECURITY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ORCA_SECURITY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Orca Security",
            iconPath="/static/services/orca_security.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
