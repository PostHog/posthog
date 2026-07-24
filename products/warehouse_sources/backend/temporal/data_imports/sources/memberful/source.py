from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.memberful import (
    MemberfulSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MemberfulSource(SimpleSource[MemberfulSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MEMBERFUL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MEMBERFUL,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Memberful (Patreon, Inc.)",
            iconPath="/static/services/memberful.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
