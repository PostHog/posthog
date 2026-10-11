from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.gcp_recaptcha_enterprise._config import GcpRecaptchaEnterpriseSourceConfig


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
