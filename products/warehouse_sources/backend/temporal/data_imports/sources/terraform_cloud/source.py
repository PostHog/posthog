from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    TerraformCloudSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TerraformCloudSource(SimpleSource[TerraformCloudSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TERRAFORMCLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TERRAFORM_CLOUD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="HashiCorp (HCP Terraform / Terraform Cloud)",
            iconPath="/static/services/terraform_cloud.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
