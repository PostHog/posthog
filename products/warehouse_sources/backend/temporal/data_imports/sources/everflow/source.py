from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import NOT_DETECTABLE
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
from products.warehouse_sources.backend.temporal.data_imports.sources.everflow.everflow import (
    EverflowResumeConfig,
    everflow_source,
    validate_credentials as validate_everflow_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.everflow.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LOOKBACK,
    MERGE_ONLY,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.everflow import (
    EverflowSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

DEFAULT_CURRENCY = "USD"


@SourceRegistry.register
class EverflowSource(ResumableSource[EverflowSourceConfig, EverflowResumeConfig]):
    codebase_detection = NOT_DETECTABLE

    lists_tables_without_credentials = True
    api_docs_url = "https://developers.everflow.io/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EVERFLOW

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Everflow rejected the API key. Check the key and the region in the source settings.",
            "403 Client Error: Forbidden for url": "This Everflow key cannot read network data. Use a network API key from Security settings in Everflow.",
            "daily report for": (
                "One day of Everflow's daily performance report has more than 10,000 offer and partner pairs, "
                "which Everflow cannot return in one request. Deselect the daily_performance table."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.everflow.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: EverflowSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=MERGE_ONLY, default_incremental_lookback_seconds=LOOKBACK
        )

    def validate_credentials(
        self,
        config: EverflowSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        currency_code = (config.currency_code or "").strip()
        if currency_code and not (len(currency_code) == 3 and currency_code.isascii() and currency_code.isalpha()):
            return False, "Reporting currency must be a three-letter code, such as USD."
        return validate_everflow_credentials(config.api_key, config.region)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[EverflowResumeConfig]:
        return ResumableSourceManager[EverflowResumeConfig](inputs, EverflowResumeConfig)

    def source_for_pipeline(
        self,
        config: EverflowSourceConfig,
        resumable_source_manager: ResumableSourceManager[EverflowResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return everflow_source(
            api_key=config.api_key,
            region=config.region,
            endpoint=inputs.schema_name,
            currency_code=(config.currency_code or DEFAULT_CURRENCY).strip().upper(),
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
            name=ExternalDataSourceType.EVERFLOW,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["affiliate", "partner marketing"],
            label="Everflow",
            caption="Sync offers, partners, advertisers, conversions and daily performance from your Everflow network.",
            docsUrl="https://posthog.com/docs/cdp/sources/everflow",
            iconPath="/static/services/everflow.png",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Network API key",
                        caption="Create one under Control center > Security > API keys in Everflow.",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US", value="us"),
                            SourceFieldSelectConfigOption(label="EU", value="eu"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="currency_code",
                        label="Reporting currency",
                        caption="Three-letter currency code for the daily performance table.",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder=DEFAULT_CURRENCY,
                        secret=False,
                    ),
                ],
            ),
        )
