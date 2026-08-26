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

from products.warehouse_sources.backend.temporal.data_imports.sources.adyen.adyen import (
    AdyenResumeConfig,
    adyen_source,
    validate_credentials as validate_adyen_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adyen.settings import (
    ADYEN_ENDPOINTS,
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.adyen import AdyenSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

CAPTION = """Connect your Adyen account to sync payments data into the PostHog Data warehouse.

Create an API credential in your Adyen Customer Area under **Developers > API credentials**, then paste its API key below. Which tables you can sync depends on what that credential can reach:

- **Transactions, transfers, account holders and balance accounts** need an Adyen for Platforms or Adyen Issuing integration. Add your balance platform ID too.
- **Settlement detail reports** need a merchant account and the **Merchant Report Download** role. Adyen only creates these files once you turn on the settlement details report in your Customer Area.
- **Companies and merchant accounts** come from the Management API and need an account read role.

Pick the environment that matches where you created the API key — a test key won't work against live."""


@SourceRegistry.register
class AdyenSource(ResumableSource[AdyenSourceConfig, AdyenResumeConfig]):
    # Adyen versions each of its APIs separately (Transfers v4, Configuration v2, Management v3),
    # so there is no single version token to pin for the source as a whole.
    api_docs_url = "https://docs.adyen.com/api-explorer/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ADYEN

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Adyen rejected the API key. Check the key, and that it matches the environment you selected.",
            "403 Client Error: Forbidden": "Adyen denied access. Check that the API credential has the roles needed for the tables you're syncing.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.adyen.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AdyenSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Adyen accounts reach either the balance platform tables or the merchant report, rarely
        # both, so a table whose identifier is missing starts unselected instead of failing its
        # first sync.
        has_platform = bool((config.balance_platform or "").strip())
        has_merchant = bool((config.merchant_account or "").strip())
        should_sync_default = {
            name: (has_platform or not endpoint.requires_balance_platform)
            and (has_merchant or not endpoint.requires_merchant_account)
            for name, endpoint in ADYEN_ENDPOINTS.items()
        }

        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            descriptions=ENDPOINT_DESCRIPTIONS,
            should_sync_default=should_sync_default,
        )

    def validate_credentials(
        self,
        config: AdyenSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_adyen_credentials(
            environment=config.environment,
            api_key=config.api_key,
            balance_platform=config.balance_platform,
            merchant_account=config.merchant_account,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AdyenResumeConfig]:
        return ResumableSourceManager[AdyenResumeConfig](inputs, AdyenResumeConfig)

    def source_for_pipeline(
        self,
        config: AdyenSourceConfig,
        resumable_source_manager: ResumableSourceManager[AdyenResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return adyen_source(
            environment=config.environment,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            balance_platform=config.balance_platform,
            merchant_account=config.merchant_account,
            start_date=config.start_date,
            settlement_report_start_batch=config.settlement_report_start_batch,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ADYEN,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Adyen",
            caption=CAPTION,
            docsUrl="https://posthog.com/docs/cdp/sources/adyen",
            iconPath="/static/services/adyen.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="live",
                        options=[
                            SourceFieldSelectConfigOption(label="Live", value="live"),
                            SourceFieldSelectConfigOption(label="Test", value="test"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="balance_platform",
                        label="Balance platform ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="YOUR_BALANCE_PLATFORM",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="merchant_account",
                        label="Merchant account",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="YOUR_MERCHANT_ACCOUNT",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2024-01-01",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="settlement_report_start_batch",
                        label="First settlement batch number",
                        type=SourceFieldInputConfigType.NUMBER,
                        required=False,
                        placeholder="1",
                        secret=False,
                    ),
                ],
            ),
        )
