from typing import cast

from sources.amazon_selling_partner._config import AmazonSellingPartnerSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AmazonSellingPartnerSource(SimpleSource[AmazonSellingPartnerSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AMAZONSELLINGPARTNER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AMAZONSELLINGPARTNER,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Amazon Selling Partner",
            iconPath="/static/services/amazon_selling_partner.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
