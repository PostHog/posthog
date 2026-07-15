from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    SplunkObservabilityCloudSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SplunkObservabilityCloudSource(SimpleSource[SplunkObservabilityCloudSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SPLUNKOBSERVABILITYCLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SPLUNK_OBSERVABILITY_CLOUD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Splunk (Cisco) - Splunk Observability Cloud",
            iconPath="/static/services/splunk_observability_cloud.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
