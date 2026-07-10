from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GitLabSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gitlab.gitlab import (
    HOST_NOT_ALLOWED_ERROR,
    HTTP_NOT_ALLOWED_ERROR,
    GitLabResumeConfig,
    gitlab_source,
    validate_credentials as validate_gitlab_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gitlab.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GitLabSource(ResumableSource[GitLabSourceConfig, GitLabResumeConfig]):
    supported_versions = ("v4",)
    default_version = "v4"
    api_docs_url = "https://docs.gitlab.com/ee/api/rest/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GITLAB

    @property
    def connection_host_fields(self) -> list[str]:
        # `gitlab_host` is where the stored token is sent; retargeting it must re-require the token.
        return ["gitlab_host"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GIT_LAB,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="GitLab",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync issues, merge requests, commits, pipelines, and more from a GitLab project.

Create a personal access token in your GitLab **User settings > Access tokens** with the `read_api` scope.
For self-managed GitLab, set the instance URL (for example `https://gitlab.example.com`); leave it as `https://gitlab.com` for GitLab.com.""",
            iconPath="/static/services/gitlab.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/gitlab",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="gitlab_host",
                        label="GitLab instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://gitlab.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="personal_access_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="glpat-...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="project",
                        label="Project",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="group/project or numeric project id",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.gitlab.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid GitLab personal access token. Please generate a new token and reconnect.",
            "403 Client Error": "Your GitLab token lacks the required permissions (needs the `read_api` scope). Please check the token and try again.",
            "404 Client Error": "Project not found. Please verify the project id/path and the token's access.",
            HOST_NOT_ALLOWED_ERROR: "The GitLab host is not allowed. Please use a publicly reachable instance URL.",
            HTTP_NOT_ALLOWED_ERROR: "The GitLab host must use HTTPS. Please update the instance URL to use https://.",
        }

    def get_schemas(
        self,
        config: GitLabSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: GitLabSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_gitlab_credentials(config.gitlab_host, config.personal_access_token, config.project, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GitLabResumeConfig]:
        return ResumableSourceManager[GitLabResumeConfig](inputs, GitLabResumeConfig)

    def source_for_pipeline(
        self,
        config: GitLabSourceConfig,
        resumable_source_manager: ResumableSourceManager[GitLabResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return gitlab_source(
            host=config.gitlab_host,
            personal_access_token=config.personal_access_token,
            project=config.project,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
