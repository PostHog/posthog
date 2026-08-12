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
from products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments import dodopayments as api_client
from products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments.dodopayments import (
    DodoPaymentsResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments.settings import (
    DEFAULT_MODE,
    DODOPAYMENTS_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MODE_HOSTS,
    RESTATED_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dodopayments import (
    DodoPaymentsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

DODOPAYMENTS_API_KEYS_URL = "https://app.dodopayments.com/developer/api-keys"


@SourceRegistry.register
class DodoPaymentsSource(ResumableSource[DodoPaymentsSourceConfig, DodoPaymentsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Dodo Payments serves unversioned paths (`/payments`, `/subscriptions`) with no version
    # header, query param or dated release channel, so there is nothing to pin.
    api_docs_url = "https://docs.dodopayments.com/api-reference/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DODOPAYMENTS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": (
                "Dodo Payments rejected the API key. Check that the key is still active and that it "
                "matches the mode (test or live) selected on this source."
            ),
            "403 Client Error: Forbidden for url": (
                "Your Dodo Payments API key does not have permission for this resource. Grant it read "
                "access in the dashboard under Developer > API Keys and reconnect."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments.canonical_descriptions import (  # noqa: PLC0415 — lazy import of sibling metadata, per the source architecture contract
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DodoPaymentsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)
        for schema in schemas:
            endpoint = DODOPAYMENTS_ENDPOINTS[schema.name]
            schema.detected_primary_keys = list(endpoint.primary_keys)
            if endpoint.restated:
                schema.default_incremental_lookback_seconds = RESTATED_LOOKBACK_SECONDS
        return schemas

    def validate_credentials(
        self,
        config: DodoPaymentsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        is_valid, status = api_client.validate_credentials(config.api_key, config.mode)
        if is_valid:
            return True, None
        if status == 401:
            return False, (
                f"Dodo Payments rejected the API key in {config.mode} mode. A test key only works "
                "against test mode, and a live key only against live mode."
            )
        if status == 403:
            return False, (
                "This Dodo Payments API key doesn't have permission to read. Grant it read access "
                "in the dashboard under Developer > API keys and reconnect."
            )
        if status == 429:
            return False, "Dodo Payments is rate limiting these requests. Wait a moment and try again."
        if status is not None and status >= 500:
            return False, "Dodo Payments returned a server error. Try again shortly."
        return False, "Could not reach Dodo Payments with these credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DodoPaymentsResumeConfig]:
        return ResumableSourceManager[DodoPaymentsResumeConfig](inputs, DodoPaymentsResumeConfig)

    def source_for_pipeline(
        self,
        config: DodoPaymentsSourceConfig,
        resumable_source_manager: ResumableSourceManager[DodoPaymentsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return api_client.dodopayments_source(
            api_key=config.api_key,
            mode=config.mode,
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
            name=SchemaExternalDataSourceType.DODO_PAYMENTS,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Dodo Payments",
            caption=(
                "Sync payments, subscriptions, customers, refunds, disputes, payouts and your product "
                "catalog from Dodo Payments into PostHog. Create an API key in your Dodo Payments "
                f"dashboard under [Developer > API keys]({DODOPAYMENTS_API_KEYS_URL}). Read access is enough."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/dodo-payments",
            iconPath="/static/services/dodopayments.png",
            keywords=["payments", "billing", "merchant of record"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        caption=(
                            f"Create a key under [Developer > API keys]({DODOPAYMENTS_API_KEYS_URL}). "
                            "A read-only key is enough to sync."
                        ),
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="mode",
                        label="Mode",
                        required=True,
                        defaultValue=DEFAULT_MODE,
                        caption=(
                            "Dodo Payments keeps test and live data on separate hosts with separate keys. "
                            "Pick the mode your key was issued for."
                        ),
                        options=[SourceFieldSelectConfigOption(label=mode.title(), value=mode) for mode in MODE_HOSTS],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
