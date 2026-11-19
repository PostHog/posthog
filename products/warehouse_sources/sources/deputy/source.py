from typing import Optional, cast

from products.warehouse_sources.sources.deputy._config import DeputySourceConfig
from products.warehouse_sources.sources.deputy.deputy import (
    DeputyResumeConfig,
    deputy_source,
    validate_credentials as validate_deputy_credentials,
)
from products.warehouse_sources.sources.deputy.settings import API_VERSION, ENDPOINTS, INCREMENTAL_FIELDS
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
class DeputySource(ResumableSource[DeputySourceConfig, DeputyResumeConfig]):
    codebase_detection = detect(env=("^DEPUTY_",))

    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://developer.deputy.com/docs/getting-started-with-the-deputy-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DEPUTY

    @property
    def connection_host_fields(self) -> list[str]:
        # The token is sent to the host in `install_url`, so a change to it must require the token again.
        return ["install_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DEPUTY,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Deputy",
            releaseStatus=ReleaseStatus.BETA,
            caption="""Connect your Deputy install to sync employees, rosters, timesheets, leave and more.

Your Deputy URL is the address you use to sign in, for example `https://yourbusiness.au.deputy.com`.

To create a permanent token, open `https://yourbusiness.au.deputy.com/exec/devapp/oauth_clients` as an administrator, add an OAuth client, then click **Get an Access Token**. Deputy shows the token only once. The token reads the data that its user can see.
""",
            docsUrl="https://posthog.com/docs/cdp/sources/deputy",
            iconPath="/static/warehouse-sources/deputy/icon.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="install_url",
                        label="Deputy URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://yourbusiness.au.deputy.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Permanent token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Deputy rejected the permanent token. Create a new token in your Deputy install, then reconnect the source.",
            "403 Client Error: Forbidden for url": "Your Deputy token can't read one of the tables you sync. Use a token that belongs to an administrator, or turn off that table.",
            "Invalid Deputy URL": "Your Deputy URL is not valid. Use the address of your Deputy install, for example https://yourbusiness.au.deputy.com.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.deputy.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DeputySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # The `Modified` filter includes the watermark row (`ge`), so an append sync would write that
        # row again on each run. Merge deduplicates it on `Id`.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=ENDPOINTS)

    def validate_credentials(
        self,
        config: DeputySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_deputy_credentials(config.install_url, config.access_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DeputyResumeConfig]:
        return ResumableSourceManager[DeputyResumeConfig](inputs, DeputyResumeConfig)

    def source_for_pipeline(
        self,
        config: DeputySourceConfig,
        resumable_source_manager: ResumableSourceManager[DeputyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return deputy_source(
            install_url=config.install_url,
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
