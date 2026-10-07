from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.revolutmerchant import (
    RevolutMerchantSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.revolut_merchant.revolut_merchant import (
    AUTH_ERROR,
    PERMISSION_ERROR,
    VERSION_ERROR,
    RevolutMerchantResumeConfig,
    revolut_merchant_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.revolut_merchant.settings import (
    API_VERSION,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RevolutMerchantSource(ResumableSource[RevolutMerchantSourceConfig, RevolutMerchantResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = "https://developer.revolut.com/docs/api/merchant"
    supported_versions = (API_VERSION,)
    default_version = API_VERSION

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REVOLUTMERCHANT

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": PERMISSION_ERROR,
            "400 Client Error": VERSION_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.revolut_merchant.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: RevolutMerchantSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: RevolutMerchantSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(
            config.api_key, config.environment, self.resolve_api_version(api_version), schema_name
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RevolutMerchantResumeConfig]:
        return ResumableSourceManager(inputs, RevolutMerchantResumeConfig)

    def source_for_pipeline(
        self,
        config: RevolutMerchantSourceConfig,
        resumable_source_manager: ResumableSourceManager[RevolutMerchantResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return revolut_merchant_source(
            api_key=config.api_key,
            environment=config.environment,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.REVOLUTMERCHANT,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Revolut Merchant",
            iconPath="/static/services/revolut_merchant.png",
            docsUrl="https://posthog.com/docs/cdp/sources/revolut-merchant",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="Enter your Merchant Secret API key from Revolut Business. Use the key for the selected environment. "
            "The checkout Public key and Revolut Business API credentials cannot be used here.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Secret API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="",
                    ),
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        defaultValue="production",
                        required=True,
                        options=[
                            SourceFieldSelectConfigOption(label="Production", value="production"),
                            SourceFieldSelectConfigOption(label="Sandbox", value="sandbox"),
                        ],
                    ),
                ],
            ),
        )
