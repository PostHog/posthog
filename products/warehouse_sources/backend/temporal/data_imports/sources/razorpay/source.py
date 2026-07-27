from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.razorpay import (
    RazorpaySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.razorpay import (
    RazorpayResumeConfig,
    razorpay_source,
    validate_credentials as validate_razorpay_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.settings import (
    ENDPOINT_CONFIGS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RazorpaySource(ResumableSource[RazorpaySourceConfig, RazorpayResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://razorpay.com/docs/api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RAZORPAY

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.razorpay.com": "Razorpay authentication failed. Please check your key ID and key secret.",
            "400 Client Error: Bad Request for url: https://api.razorpay.com": None,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: RazorpaySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: RazorpaySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_razorpay_credentials(config.key_id, config.key_secret):
            return True, None

        return (
            False,
            "Razorpay rejected the credentials. Check that the key ID and key secret are correct and the key is active.",
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RazorpayResumeConfig]:
        return ResumableSourceManager[RazorpayResumeConfig](inputs, RazorpayResumeConfig)

    def source_for_pipeline(
        self,
        config: RazorpaySourceConfig,
        resumable_source_manager: ResumableSourceManager[RazorpayResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        endpoint_config = ENDPOINT_CONFIGS[inputs.schema_name]
        resource = razorpay_source(
            key_id=config.key_id,
            key_secret=config.key_secret,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=[endpoint_config.primary_key],
            column_hints=resource.column_hints,
            partition_count=1,
            partition_size=1,
            partition_mode="datetime",
            partition_format="week",
            partition_keys=[endpoint_config.partition_key],
            # List endpoints return newest-first and expose no sort param.
            sort_mode="desc",
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RAZORPAY,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Razorpay",
            caption="Enter your Razorpay API key pair to pull payments, orders, refunds, settlements, and subscription data into the PostHog Data warehouse. Generate a key ID and key secret in the Razorpay Dashboard under Account & Settings → API keys. Use a `rzp_live_` key for live-mode data or a `rzp_test_` key for test-mode data.",
            docsUrl="https://posthog.com/docs/cdp/sources/razorpay",
            iconPath="/static/services/razorpay.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="key_id",
                        label="Key ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="rzp_live_...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="key_secret",
                        label="Key secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
