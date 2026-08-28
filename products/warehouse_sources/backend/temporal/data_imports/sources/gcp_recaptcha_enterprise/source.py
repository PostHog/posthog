from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gcprecaptchaenterprise import (
    GcpRecaptchaEnterpriseSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GcpRecaptchaEnterpriseSource(SimpleSource[GcpRecaptchaEnterpriseSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPRECAPTCHAENTERPRISE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GCP_RECAPTCHA_ENTERPRISE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud reCAPTCHA Enterprise",
            iconPath="/static/services/gcp_recaptcha_enterprise.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
