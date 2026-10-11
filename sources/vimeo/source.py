from typing import cast

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
from sources.vimeo._config import VimeoSourceConfig
from sources.vimeo.canonical_descriptions import CANONICAL_DESCRIPTIONS
from sources.vimeo.settings import AUTH_ERROR, ENDPOINTS, PERMISSION_ERROR
from sources.vimeo.vimeo import (
    VimeoResumeConfig,
    validate_credentials as validate_vimeo_credentials,
    vimeo_source,
)


@SourceRegistry.register
class VimeoSource(ResumableSource[VimeoSourceConfig, VimeoResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("3.4",)
    default_version = "3.4"
    api_docs_url = "https://developer.vimeo.com/api/changelog"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VIMEO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": PERMISSION_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: VimeoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: VimeoSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_vimeo_credentials(config.access_token, self.resolve_api_version(api_version), schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[VimeoResumeConfig]:
        return ResumableSourceManager(inputs, VimeoResumeConfig)

    def source_for_pipeline(
        self,
        config: VimeoSourceConfig,
        resumable_source_manager: ResumableSourceManager[VimeoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return vimeo_source(
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.VIMEO,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Vimeo",
            iconPath="/static/services/vimeo.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Open your app at [Vimeo Developers](https://developer.vimeo.com/apps). "
                "Under **Generate an access token**, select **Authenticated (you)**. "
                "Enable `public` and `private` scopes to read your videos, folders, and showcases."
            ),
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    )
                ],
            ),
        )
