from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    PromptingCompanySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PromptingCompanySource(SimpleSource[PromptingCompanySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PROMPTINGCOMPANY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PROMPTING_COMPANY,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="The Prompting Company",
            iconPath="/static/services/prompting_company.png",
            keywords=["geo", "ai visibility", "llm", "share of voice"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
