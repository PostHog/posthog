from typing import Optional, cast

from sources.sdk import (
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
    _is_host_safe,
    build_endpoint_schemas,
)
from sources.teamwork._config import TeamworkSourceConfig
from sources.teamwork.canonical_descriptions import CANONICAL_DESCRIPTIONS
from sources.teamwork.settings import ENDPOINTS, INCREMENTAL_FIELDS
from sources.teamwork.teamwork import (
    TeamworkResumeConfig,
    normalize_host,
    teamwork_source,
    validate_credentials as validate_teamwork_credentials,
)


@SourceRegistry.register
class TeamworkSource(ResumableSource[TeamworkSourceConfig, TeamworkResumeConfig]):
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://apidocs.teamwork.com"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TEAMWORK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TEAMWORK,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Teamwork",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Teamwork.com site and API key to pull your Teamwork projects data into the PostHog Data warehouse.

Find your API key under **Profile → Edit my details → API & Mobile** in Teamwork. The key inherits your own permissions, so it can only sync data you can see.""",
            iconPath="/static/services/teamwork.png",
            docsUrl="https://posthog.com/docs/cdp/sources/teamwork",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="site",
                        label="Site",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="yoursite.teamwork.com",
                        secret=False,
                    ),
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

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key is sent to the host derived from `site`; retargeting it must re-require the key.
        return ["site"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your Teamwork API key is invalid or has been revoked. Generate a new key in your Teamwork profile settings, then reconnect.",
            "403 Client Error: Forbidden for url": "Your Teamwork API key does not have permission to access this data. Check the key's permissions, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TeamworkSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: TeamworkSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        host = normalize_host(config.site)

        host_is_safe, host_error = _is_host_safe(host, team_id)
        if not host_is_safe:
            return False, host_error or "Teamwork site host is not allowed"

        if validate_teamwork_credentials(host, config.api_key):
            return True, None

        return False, "Teamwork rejected the credentials. Check the site and API key are correct."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TeamworkResumeConfig]:
        return ResumableSourceManager[TeamworkResumeConfig](inputs, TeamworkResumeConfig)

    def source_for_pipeline(
        self,
        config: TeamworkSourceConfig,
        resumable_source_manager: ResumableSourceManager[TeamworkResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        host = normalize_host(config.site)

        # Re-check host safety at sync time, not just at source creation: `site` can be edited after
        # validation, and every request below sends the stored API key to it — block internal/private
        # hosts to prevent SSRF and credential redirection.
        host_is_safe, host_error = _is_host_safe(host, inputs.team_id)
        if not host_is_safe:
            raise ValueError(host_error or "Teamwork site host is not allowed")

        return teamwork_source(
            host=host,
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
