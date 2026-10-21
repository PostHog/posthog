from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.asaas.asaas import (
    AsaasResumeConfig,
    asaas_source,
    validate_credentials as validate_asaas_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.asaas.settings import (
    ENDPOINTS,
    FANOUT_PARENTS,
    INCREMENTAL_FIELDS,
    PARTITION_KEYS,
    PRIMARY_KEYS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.asaas import AsaasSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AsaasSource(ResumableSource[AsaasSourceConfig, AsaasResumeConfig]):
    codebase_detection = detect(env=("^ASAAS_",), maven=("com.asaas:api-sdk",))

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://docs.asaas.com/reference/comece-por-aqui"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ASAAS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Asaas API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error": "Your Asaas API key doesn't have permission for this request. Check the key's account and try again.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.asaas.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AsaasSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: AsaasSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_asaas_credentials(config.api_key, config.environment):
            return True, None

        return False, "Invalid credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AsaasResumeConfig]:
        return ResumableSourceManager[AsaasResumeConfig](inputs, AsaasResumeConfig)

    def source_for_pipeline(
        self,
        config: AsaasSourceConfig,
        resumable_source_manager: ResumableSourceManager[AsaasResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        resource = asaas_source(
            api_key=config.api_key,
            environment=config.environment,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
        partition_key = PARTITION_KEYS.get(inputs.schema_name)
        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=PRIMARY_KEYS.get(inputs.schema_name, ["id"]),
            partition_mode="datetime" if partition_key else None,
            partition_format="month" if partition_key else None,
            partition_keys=[partition_key] if partition_key else None,
            # The fan-out saves no checkpoint, so a shutdown hand-off would only restart the sweep.
            supports_resume=inputs.schema_name not in FANOUT_PARENTS,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ASAAS,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Asaas",
            caption=(
                "Connect your Asaas account using an API key to sync customers, payments, "
                "subscriptions, transfers, installments, invoices, received splits, Pix "
                "transactions, payment links, dunnings, bill payments, and your account "
                "statement. Find your key in Asaas under "
                "**Integrações** > **API**."
            ),
            keywords=["billing", "payments", "brazil"],
            iconPath="/static/services/asaas.png",
            docsUrl="https://posthog.com/docs/cdp/sources/asaas",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="production",
                        options=[
                            SourceFieldSelectConfigOption(label="Production (api.asaas.com)", value="production"),
                            SourceFieldSelectConfigOption(label="Sandbox (api-sandbox.asaas.com)", value="sandbox"),
                        ],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.GA,
        )
