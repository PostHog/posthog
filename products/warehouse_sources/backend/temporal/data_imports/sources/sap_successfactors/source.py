from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    SapSuccessFactorsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SapSuccessFactorsSource(SimpleSource[SapSuccessFactorsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SAPSUCCESSFACTORS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SAP_SUCCESS_FACTORS,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="SAP SuccessFactors",
            iconPath="/static/services/sap_successfactors.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
