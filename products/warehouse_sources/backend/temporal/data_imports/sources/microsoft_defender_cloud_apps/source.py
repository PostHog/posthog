from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.microsoftdefendercloudapps import (
    MicrosoftDefenderCloudAppsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MicrosoftDefenderCloudAppsSource(SimpleSource[MicrosoftDefenderCloudAppsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTDEFENDERCLOUDAPPS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MICROSOFT_DEFENDER_CLOUD_APPS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Defender for Cloud Apps",
            iconPath="/static/services/microsoft_defender_cloud_apps.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
