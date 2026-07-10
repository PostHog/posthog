from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DenoDeploySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DenoDeploySource(SimpleSource[DenoDeploySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DENODEPLOY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DENO_DEPLOY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Deno Deploy",
            iconPath="/static/services/deno_deploy.png",
            keywords=["deno", "deploy", "serverless", "edge"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
