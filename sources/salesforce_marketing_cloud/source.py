from typing import cast

from sources.salesforce_marketing_cloud._config import SalesforceMarketingCloudSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class SalesforceMarketingCloudSource(SimpleSource[SalesforceMarketingCloudSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SALESFORCEMARKETINGCLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SALESFORCEMARKETINGCLOUD,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            keywords=["sfmc"],
            label="Salesforce Marketing Cloud",
            iconPath="/static/services/salesforce_marketing_cloud.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
