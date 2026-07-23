from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsmacie import (
    AwsMacieSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsMacieSource(SimpleSource[AwsMacieSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSMACIE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AWS_MACIE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Amazon Web Services (Amazon Macie)",
            iconPath="/static/services/aws_macie.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
