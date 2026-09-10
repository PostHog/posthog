from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awssystemsmanager import (
    AwsSystemsManagerSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsSystemsManagerSource(SimpleSource[AwsSystemsManagerSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSSYSTEMSMANAGER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AWS_SYSTEMS_MANAGER,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Amazon Web Services (AWS Systems Manager)",
            iconPath="/static/services/aws_systems_manager.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
