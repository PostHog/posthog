from typing import Optional, cast

from products.warehouse_sources.sources.samcart._config import SamCartSourceConfig
from products.warehouse_sources.sources.samcart.samcart import SamCartResumeConfig, check_access, samcart_source
from products.warehouse_sources.sources.samcart.settings import API_VERSION, ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
    detect,
)


@SourceRegistry.register
class SamCartSource(ResumableSource[SamCartSourceConfig, SamCartResumeConfig]):
    codebase_detection = detect(env=("^SAMCART_",))

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://developer.samcart.com/v2/index.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SAMCART

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SAMCART,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="SamCart",
            releaseStatus=ReleaseStatus.BETA,
            caption="""Enter your SamCart API key to pull your SamCart orders, charges, subscriptions, and refunds into the PostHog Data warehouse.

Create a key in the SamCart dashboard under **Settings → API Keys**. A **Read only** key is enough. Your SamCart plan must include API access.
""",
            iconPath="/static/services/samcart.png",
            docsUrl="https://posthog.com/docs/cdp/sources/samcart",
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
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.samcart.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.samcart.com": "SamCart rejected your API key. Create a new key under Settings → API Keys in SamCart, then reconnect the source.",
            "403 Client Error: Forbidden for url: https://api.samcart.com": "SamCart refused access. Check that your SamCart plan includes API access and that your account is active, then reconnect the source.",
        }

    def get_schemas(
        self,
        config: SamCartSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: SamCartSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        status = check_access(config.api_key)
        if status == 200:
            return True, None
        if status == 401:
            return False, "Invalid SamCart API key"
        if status == 403:
            return False, "Your SamCart plan doesn't include API access, or your SamCart account isn't active"
        if status is None:
            return False, "Could not connect to SamCart"
        return False, f"SamCart returned HTTP {status}"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SamCartResumeConfig]:
        return ResumableSourceManager[SamCartResumeConfig](inputs, SamCartResumeConfig)

    def source_for_pipeline(
        self,
        config: SamCartSourceConfig,
        resumable_source_manager: ResumableSourceManager[SamCartResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return samcart_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
