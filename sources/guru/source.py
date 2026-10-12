from typing import Optional, cast

from sources.guru._config import GuruSourceConfig
from sources.guru.guru import (
    GuruResumeConfig,
    guru_source,
    validate_credentials as validate_guru_credentials,
)
from sources.guru.settings import ENDPOINTS, INCREMENTAL_FIELDS
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
    build_endpoint_schemas,
)


@SourceRegistry.register
class GuruSource(ResumableSource[GuruSourceConfig, GuruResumeConfig]):
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://developer.getguru.com"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GURU

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from sources.guru.canonical_descriptions import CANONICAL_DESCRIPTIONS  # noqa: PLC0415

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.getguru.com": "Guru authentication failed. Please check your username and API token.",
            "403 Client Error: Forbidden for url: https://api.getguru.com": "Guru denied access. Please check that your API token has the required permissions.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GURU,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Guru",
            caption="""Enter your Guru API credentials to pull your Guru knowledge base data into the PostHog Data warehouse.

You authenticate with your Guru account email and a user API token. A Guru admin can generate user tokens from [Settings > Apps and integrations > API access](https://app.getguru.com/settings/integrations/api-access). Use a user token rather than a collection token — collection tokens are read-only and scoped to a single collection.""",
            iconPath="/static/services/guru.png",
            docsUrl="https://posthog.com/docs/cdp/sources/guru",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="username",
                        label="Username (email)",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=True,
                        placeholder="user@company.com",
                        secret=False,
                    ),
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

    def get_schemas(
        self,
        config: GuruSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self, config: GuruSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        if validate_guru_credentials(config.username, config.api_token):
            return True, None

        return False, "Invalid Guru API credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GuruResumeConfig]:
        return ResumableSourceManager[GuruResumeConfig](inputs, GuruResumeConfig)

    def source_for_pipeline(
        self,
        config: GuruSourceConfig,
        resumable_source_manager: ResumableSourceManager[GuruResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return guru_source(
            username=config.username,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
