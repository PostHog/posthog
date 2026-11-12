from typing import Optional, cast

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
from products.warehouse_sources.sources.wise._config import WiseSourceConfig
from products.warehouse_sources.sources.wise.settings import (
    API_VERSION,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    INCREMENTAL_LOOKBACK,
    MERGE_ONLY_ENDPOINTS,
)
from products.warehouse_sources.sources.wise.wise import (
    WiseResumeConfig,
    get_endpoint_permissions as get_wise_endpoint_permissions,
    validate_credentials as validate_wise_credentials,
    wise_source,
)


@SourceRegistry.register
class WiseSource(ResumableSource[WiseSourceConfig, WiseResumeConfig]):
    # Wise publishes no official API SDK, so only the env key names give it away.
    codebase_detection = detect(env=("^WISE_API_", "^TRANSFERWISE_"))

    lists_tables_without_credentials = True  # get_schemas reads a static catalog with no I/O

    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://docs.wise.com/guides/developer/global-versioning"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WISE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.wise.com": "Wise rejected your API token. Create a new personal API token in Wise and reconnect the source.",
            "403 Client Error: Forbidden for url: https://api.wise.com": "Your Wise API token can't read one of the tables you sync. Turn off that table, or use a token from a Wise business account.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.wise.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: WiseSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            merge_only=MERGE_ONLY_ENDPOINTS,
            default_incremental_lookback_seconds=INCREMENTAL_LOOKBACK,
        )

    def validate_credentials(
        self,
        config: WiseSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_wise_credentials(config.api_token)

    def get_endpoint_permissions(
        self, config: WiseSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        return get_wise_endpoint_permissions(config.api_token, endpoints)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WiseResumeConfig]:
        return ResumableSourceManager[WiseResumeConfig](inputs, WiseResumeConfig)

    def source_for_pipeline(
        self,
        config: WiseSourceConfig,
        resumable_source_manager: ResumableSourceManager[WiseResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return wise_source(
            token=config.api_token,
            endpoint_name=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.WISE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Wise",
            keywords=["transferwise"],
            caption=(
                "Import profiles, balances, transfers, recipients and activities from your Wise account. "
                "In Wise, open your account settings, select **Accounting integrations**, then go to "
                "**Developer tools** > **API tokens** and create a token. Personal API tokens are only "
                "available for Wise business accounts. Wise limits what some tokens can read, for example "
                "for businesses in the EU and the UK. The table list marks each table that your token "
                "can't read."
            ),
            iconPath="/static/warehouse-sources/wise/icon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/wise",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Personal API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
