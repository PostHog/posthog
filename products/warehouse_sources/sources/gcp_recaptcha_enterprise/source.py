from typing import cast

from products.warehouse_sources.sources.gcp_recaptcha_enterprise._config import GcpRecaptchaEnterpriseSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpRecaptchaEnterpriseSource(SimpleSource[GcpRecaptchaEnterpriseSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPRECAPTCHAENTERPRISE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPRECAPTCHAENTERPRISE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud reCAPTCHA Enterprise",
            iconPath="/static/services/gcp_recaptcha_enterprise.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
