from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.aws_trusted_advisor._config import AwsTrustedAdvisorSourceConfig


@SourceRegistry.register
class AwsTrustedAdvisorSource(SimpleSource[AwsTrustedAdvisorSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSTRUSTEDADVISOR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSTRUSTEDADVISOR,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Amazon Web Services (AWS Trusted Advisor)",
            iconPath="/static/services/aws_trusted_advisor.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
