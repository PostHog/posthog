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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.stackoverflowforteams import (
    StackOverflowForTeamsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stack_overflow_for_teams.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stack_overflow_for_teams.stack_overflow_for_teams import (
    StackOverflowForTeamsResumeConfig,
    stack_overflow_for_teams_source,
    validate_credentials as validate_stack_overflow_for_teams_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class StackOverflowForTeamsSource(
    ResumableSource[StackOverflowForTeamsSourceConfig, StackOverflowForTeamsResumeConfig]
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://api.stackoverflowteams.com/docs"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STACKOVERFLOWFORTEAMS

    @property
    def connection_host_fields(self) -> list[str]:
        # The PAT is sent to api.stackoverflowteams.com/v3/teams/<team>, so retargeting the
        # team must re-require it.
        return ["team"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.STACK_OVERFLOW_FOR_TEAMS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Stack Overflow (Prosus/Stack Exchange)",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Stack Overflow for Teams team name and a Personal access token to pull your internal Q&A knowledge base — questions, answers, articles, tags, users, and collections — into the PostHog Data warehouse.

Create a token under **Account Settings → Personal access tokens**, scoped to this team. Read-only (Basic) access is sufficient — you don't need to grant write access.""",
            iconPath="/static/services/stack_overflow_for_teams.png",
            docsUrl="https://posthog.com/docs/cdp/sources/stack-overflow-for-teams",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="team",
                        label="Team name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="engineering",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.stack_overflow_for_teams.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Your Stack Overflow for Teams personal access token is invalid or has expired. Create a new token and reconnect.",
            "403 Client Error: Forbidden": "Your Stack Overflow for Teams personal access token doesn't have access to this team or resource. Check the token's team scope, then reconnect.",
        }

    def get_schemas(
        self,
        config: StackOverflowForTeamsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: StackOverflowForTeamsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            ok, status_code = validate_stack_overflow_for_teams_credentials(config.team, config.api_token)
        except ValueError as e:
            return False, str(e)

        if ok:
            return True, None
        if status_code == 401:
            return False, "Invalid Stack Overflow for Teams personal access token"
        return (
            False,
            "Could not connect to Stack Overflow for Teams with the provided team name and personal access token",
        )

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[StackOverflowForTeamsResumeConfig]:
        return ResumableSourceManager[StackOverflowForTeamsResumeConfig](inputs, StackOverflowForTeamsResumeConfig)

    def source_for_pipeline(
        self,
        config: StackOverflowForTeamsSourceConfig,
        resumable_source_manager: ResumableSourceManager[StackOverflowForTeamsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return stack_overflow_for_teams_source(
            team=config.team,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
