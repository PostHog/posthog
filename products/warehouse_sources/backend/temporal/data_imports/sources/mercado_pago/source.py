from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mercadopago import (
    MercadoPagoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.mercado_pago import (
    MercadoPagoResumeConfig,
    mercado_pago_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MercadoPagoSource(ResumableSource[MercadoPagoSourceConfig, MercadoPagoResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = "https://www.mercadopago.com.br/developers/en/changelog"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MERCADOPAGO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": AUTH_ERROR,
            "code=invalid_token": AUTH_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MercadoPagoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only={"payments"})

    def validate_credentials(
        self,
        config: MercadoPagoSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MercadoPagoResumeConfig]:
        return ResumableSourceManager(inputs, MercadoPagoResumeConfig)

    def source_for_pipeline(
        self,
        config: MercadoPagoSourceConfig,
        resumable_source_manager: ResumableSourceManager[MercadoPagoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return mercado_pago_source(config, inputs, resumable_source_manager)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MERCADOPAGO,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Mercado Pago (Mercado Libre)",
            iconPath="/static/services/mercado_pago.png",
            caption="Open your application in Your integrations. Copy its access token from Production > Production credentials. "
            "Payments can import only the most recent year of history.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    )
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
