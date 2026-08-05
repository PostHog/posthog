from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awssagemaker import (
    AwsSagemakerSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsSagemakerSource(SimpleSource[AwsSagemakerSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSSAGEMAKER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AWS_SAGEMAKER,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Amazon Web Services (Amazon SageMaker)",
            iconPath="/static/services/aws_sagemaker.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
