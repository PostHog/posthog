from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rentcast import (
    RentCastSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rentcast.rentcast import (
    INVALID_ZIP_CODES_ERROR,
    MISSING_ZIP_CODES_ERROR,
    RentCastResumeConfig,
    parse_zip_codes,
    rentcast_source,
    validate_credentials as _validate_rentcast_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rentcast.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MARKETS_ENDPOINT,
    RENTCAST_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RentCastSource(ResumableSource[RentCastSourceConfig, RentCastResumeConfig]):
    codebase_detection = detect(env=("^(RENT_CAST|RENTCAST)_",))

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://developers.rentcast.io/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RENTCAST

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.RENTCAST,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="RentCast",
            releaseStatus=ReleaseStatus.BETA,
            caption="""Enter your RentCast API key to pull US real estate data into the PostHog Data warehouse.

You can create an API key under **API dashboard** in [RentCast](https://app.rentcast.io/app/api). The key grants read access to property records, active sale and rental listings, and market statistics.

To sync the **markets** table, enter the ZIP codes you want market statistics for. Each ZIP code uses one RentCast API request per sync.
""",
            iconPath="/static/services/rentcast.png",
            docsUrl="https://posthog.com/docs/cdp/sources/rentcast",
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
                        name="zip_codes",
                        label="ZIP codes for market statistics",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="29611, 78701",
                        caption="A comma-separated list of 5-digit US ZIP codes. Only the markets table uses it.",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.rentcast.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.rentcast.io": "Your RentCast API key is invalid or has been revoked. Generate a new key in the RentCast API dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.rentcast.io": "Your RentCast API key does not have access to this data. Check the key's plan and permissions, then reconnect.",
            MISSING_ZIP_CODES_ERROR: "Add one or more ZIP codes to the RentCast source settings to sync the markets table.",
            INVALID_ZIP_CODES_ERROR: "Correct the ZIP codes in the RentCast source settings. Each one must be a 5-digit US ZIP code.",
        }

    def get_schemas(
        self,
        config: RentCastSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — RentCast's list endpoints expose no reliably
        # ordered server-side timestamp filter, so there is no incremental cursor to advance.
        # `markets` needs ZIP codes to sync, so it stays off by default until some are configured.
        try:
            has_zip_codes = bool(parse_zip_codes(config.zip_codes))
        except ValueError:
            has_zip_codes = False
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            should_sync_default={MARKETS_ENDPOINT: has_zip_codes},
        )

    def validate_credentials(
        self,
        config: RentCastSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            parse_zip_codes(config.zip_codes)
        except ValueError as error:
            return False, str(error)
        # The API key is account-wide, so a single probe validates access to every schema.
        return _validate_rentcast_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RentCastResumeConfig]:
        return ResumableSourceManager[RentCastResumeConfig](inputs, RentCastResumeConfig)

    def source_for_pipeline(
        self,
        config: RentCastSourceConfig,
        resumable_source_manager: ResumableSourceManager[RentCastResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in RENTCAST_ENDPOINTS:
            raise ValueError(f"Unknown RentCast schema '{inputs.schema_name}'")

        return rentcast_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=None,  # every RentCast endpoint is full refresh
            zip_codes=config.zip_codes,
        )
