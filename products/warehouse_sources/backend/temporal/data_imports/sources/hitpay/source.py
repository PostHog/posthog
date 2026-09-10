from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hitpay import HitpaySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.hitpay import (
    HitpayResumeConfig,
    hitpay_source,
    validate_credentials as validate_hitpay_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HitpaySource(ResumableSource[HitpaySourceConfig, HitpayResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # HitPay's API is served unversioned at /v1, with no other version ever documented or
    # offered — not a real version choice to pin.
    api_docs_url = "https://docs.hitpayapp.com/reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HITPAY

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Your HitPay API key is invalid or has been revoked. Please generate a new key and reconnect.",
            "403 Client Error: Forbidden": "Your HitPay API key does not have permission to access this data.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: HitpaySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: HitpaySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_hitpay_credentials(config.api_key, config.platform_api_key, config.environment)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HitpayResumeConfig]:
        return ResumableSourceManager[HitpayResumeConfig](inputs, HitpayResumeConfig)

    def source_for_pipeline(
        self,
        config: HitpaySourceConfig,
        resumable_source_manager: ResumableSourceManager[HitpayResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return hitpay_source(
            api_key=config.api_key,
            platform_api_key=config.platform_api_key or None,
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

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HITPAY,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="HitPay",
            caption=(
                "Connect your HitPay account using an API key to sync payment requests, charges, "
                "subscription plans, customers, and recurring billing. Find your key in the HitPay "
                "dashboard under **Settings** > **Payment Gateway**."
            ),
            keywords=["payments", "paynow", "duitnow", "billing"],
            docsUrl="https://posthog.com/docs/cdp/sources/hitpay",
            iconPath="/static/services/hitpay.png",
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
                    SourceFieldInputConfig(
                        name="platform_api_key",
                        label="Platform API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                        caption="Only needed for HitPay platform accounts. Leave blank otherwise.",
                    ),
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="production",
                        options=[
                            SourceFieldSelectConfigOption(label="Production (api.hit-pay.com)", value="production"),
                            SourceFieldSelectConfigOption(label="Sandbox (api.sandbox.hit-pay.com)", value="sandbox"),
                        ],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
