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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GitBookSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.gitbook import (
    GitBookResumeConfig,
    gitbook_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.settings import (
    ENDPOINTS,
    GITBOOK_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GitBookSource(ResumableSource[GitBookSourceConfig, GitBookResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GITBOOK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GIT_BOOK,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="GitBook",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your GitBook API token to pull your documentation workspace into the PostHog Data warehouse.

You can create a personal access token under **Account settings → Developer** in [GitBook](https://app.gitbook.com/account/developer). The token inherits your account permissions and grants read access to your organizations, spaces, collections, sites, members, teams, change requests, and comments.
""",
            iconPath="/static/services/gitbook.png",
            docsUrl="https://posthog.com/docs/cdp/sources/gitbook",
            keywords=["docs", "documentation", "knowledge base", "wiki"],
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
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.gitbook.com": "Your GitBook API token is invalid or has been revoked. Generate a new token under Account settings → Developer, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.gitbook.com": "Your GitBook API token does not have access to this data. Check the token owner's organization permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: GitBookSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — GitBook's list endpoints expose no server-side
        # updated-after/since filter, so there is no timestamp cursor to advance an incremental sync.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: GitBookSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # A single probe of `/user` confirms the token is genuine; per-endpoint access follows the
        # token owner's permissions and is surfaced at sync time via get_non_retryable_errors.
        return validate_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GitBookResumeConfig]:
        return ResumableSourceManager[GitBookResumeConfig](inputs, GitBookResumeConfig)

    def source_for_pipeline(
        self,
        config: GitBookSourceConfig,
        resumable_source_manager: ResumableSourceManager[GitBookResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in GITBOOK_ENDPOINTS:
            raise ValueError(f"Unknown GitBook schema '{inputs.schema_name}'")

        return gitbook_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
