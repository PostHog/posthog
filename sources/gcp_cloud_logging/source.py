from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.gcp_cloud_logging._config import GcpCloudLoggingSourceConfig


@SourceRegistry.register
class GcpCloudLoggingSource(SimpleSource[GcpCloudLoggingSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCLOUDLOGGING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPCLOUDLOGGING,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud Platform",
            iconPath="/static/services/gcp_cloud_logging.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
