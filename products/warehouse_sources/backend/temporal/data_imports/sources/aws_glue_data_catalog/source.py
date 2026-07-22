from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsgluedatacatalog import (
    AwsGlueDataCatalogSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsGlueDataCatalogSource(SimpleSource[AwsGlueDataCatalogSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSGLUEDATACATALOG

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AWS_GLUE_DATA_CATALOG,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Amazon Web Services (AWS Glue)",
            iconPath="/static/services/aws_glue_data_catalog.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
