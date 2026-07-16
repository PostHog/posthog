from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OctopusDeploySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OctopusDeploySource(SimpleSource[OctopusDeploySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OCTOPUSDEPLOY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OCTOPUS_DEPLOY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Octopus Deploy",
            iconPath="/static/services/octopus_deploy.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
