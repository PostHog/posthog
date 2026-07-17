from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AwsCloudTrailSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsCloudTrailSource(SimpleSource[AwsCloudTrailSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSCLOUDTRAIL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AWS_CLOUD_TRAIL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AWS CloudTrail",
            iconPath="/static/services/aws_cloudtrail.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
