from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OracleEbsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OracleEbsSource(SimpleSource[OracleEbsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ORACLEEBS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ORACLE_EBS,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            keywords=["oracle e-business suite", "ebs"],
            label="Oracle EBS",
            iconPath="/static/services/oracle.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
