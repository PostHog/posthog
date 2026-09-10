from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gcpdataplex import (
    GcpDataplexSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GcpDataplexSource(SimpleSource[GcpDataplexSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPDATAPLEX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GCP_DATAPLEX,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud (Dataplex)",
            iconPath="/static/services/gcp_dataplex.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
