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
from products.warehouse_sources.sources.wistia._config import WistiaSourceConfig
from products.warehouse_sources.sources.wistia.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    WISTIA_API_VERSION,
    WISTIA_ENDPOINTS,
)
from products.warehouse_sources.sources.wistia.wistia import (
    WistiaResumeConfig,
    validate_credentials as validate_wistia_credentials,
    wistia_source,
)


@SourceRegistry.register
class WistiaSource(ResumableSource[WistiaSourceConfig, WistiaResumeConfig]):
    codebase_detection = detect(
        script_hosts=("fast.wistia.com", "fast.wistia.net"),
        npm=("@wistia/wistia-player", "@wistia/wistia-player-react"),
    )

    lists_tables_without_credentials = True  # static endpoint catalog, so the public docs can list the tables
    # Wistia's modern API takes a dated release in the X-Wistia-API-Version header.
    supported_versions = (WISTIA_API_VERSION,)
    default_version = WISTIA_API_VERSION
    api_docs_url = "https://docs.wistia.com/docs/migration-from-v1-guide"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WISTIA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.WISTIA,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Wistia",
            releaseStatus=ReleaseStatus.BETA,
            caption="""Enter a Wistia API token to sync your videos, folders, channels, webinars, and viewer stats into the PostHog Data warehouse.

Only the account owner can create API tokens. Go to the [API page of your Wistia account settings](https://account.wistia.com/account/api) and create a token with these permissions:
- **Read all folder and media data** for media, folders, subfolders, captions, channels, and channel episodes
- **Read all data** for tags and webinars
- **Read detailed stats** for visitors, events, and the stats tables""",
            iconPath="/static/services/wistia.png",
            docsUrl="https://posthog.com/docs/cdp/sources/wistia",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.wistia.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Wistia returns 401 both for a wrong token and for a token without the permission an
            # endpoint needs.
            "401 Client Error: Unauthorized for url: https://api.wistia.com": "Wistia rejected the API token, or the token doesn't have the permission this table needs. Check the token's permissions in your Wistia account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.wistia.com": "Your Wistia plan doesn't include the data in this table, for example webinars. Turn off the table, or upgrade your Wistia plan.",
        }

    def get_schemas(
        self,
        config: WistiaSourceConfig,
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
            # The incremental filters take a day, not a time, so the watermark day is read again.
            # Append would store that day twice.
            merge_only=tuple(INCREMENTAL_FIELDS.keys()),
            descriptions={
                name: endpoint.description for name, endpoint in WISTIA_ENDPOINTS.items() if endpoint.description
            },
            should_sync_default={name: endpoint.should_sync_default for name, endpoint in WISTIA_ENDPOINTS.items()},
        )

    def validate_credentials(
        self,
        config: WistiaSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_wistia_credentials(config.api_token, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WistiaResumeConfig]:
        return ResumableSourceManager[WistiaResumeConfig](inputs, WistiaResumeConfig)

    def source_for_pipeline(
        self,
        config: WistiaSourceConfig,
        resumable_source_manager: ResumableSourceManager[WistiaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return wistia_source(
            api_token=config.api_token,
            api_version=self.resolve_api_version(inputs.api_version),
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
