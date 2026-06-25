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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PaystackSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.paystack.paystack import (
    PaystackResumeConfig,
    paystack_source,
    validate_credentials as validate_paystack_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paystack.settings import (
    ENDPOINTS,
    PAYSTACK_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PaystackSource(ResumableSource[PaystackSourceConfig, PaystackResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PAYSTACK

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.paystack.co": "Paystack authentication failed. Please check that your secret API key is valid.",
            "403 Client Error: Forbidden for url: https://api.paystack.co": "Paystack denied access. Please check that your secret API key has the required permissions.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.paystack.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PAYSTACK,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Paystack",
            caption="""Enter your Paystack secret API key to pull your Paystack data into the PostHog Data warehouse.

You can find your secret key (it starts with `sk_live_` or `sk_test_`) under **Settings → API Keys & Webhooks** in your [Paystack dashboard](https://dashboard.paystack.com/#/settings/developers). The key has read access to your integration's data.""",
            iconPath="/static/services/paystack.png",
            docsUrl="https://posthog.com/docs/cdp/sources/paystack",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="secret_api_key",
                        label="Secret API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk_live_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: PaystackSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: PaystackSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_paystack_credentials(config.secret_api_key):
            return True, None

        return False, "Invalid Paystack secret API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PaystackResumeConfig]:
        return ResumableSourceManager[PaystackResumeConfig](inputs, PaystackResumeConfig)

    def source_for_pipeline(
        self,
        config: PaystackSourceConfig,
        resumable_source_manager: ResumableSourceManager[PaystackResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        resource = paystack_source(
            secret_api_key=config.secret_api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=[PAYSTACK_ENDPOINTS[inputs.schema_name].primary_key],
            column_hints=resource.column_hints,
        )
