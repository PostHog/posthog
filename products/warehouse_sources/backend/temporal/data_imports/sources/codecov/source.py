from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.codecov.codecov import (
    CodecovResumeConfig,
    codecov_source,
    validate_credentials as validate_codecov_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.codecov.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CodecovSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

_ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    "repos": "All repositories Codecov knows for the owner, with their latest coverage totals",
    "commits": "Commits with coverage uploads on each repository's default branch, newest-first",
    "coverage_trend": "Daily min/max/avg coverage time series per repository (default branch)",
    "flags": "Current coverage percentage per flag, per repository",
    "components": "Current coverage percentage per component, per repository",
}


@SourceRegistry.register
class CodecovSource(ResumableSource[CodecovSourceConfig, CodecovResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CODECOV

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored token is sent to api.codecov.io scoped by git provider + owner and filtered
        # by the repository allow-list, so retargeting any of these must force re-entry of the
        # token — otherwise an editor without it could point it at another owner/repo the token
        # can read and sync that private data into the warehouse.
        return ["service", "owner_username", "repositories"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CODECOV,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Codecov (Sentry)",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Codecov API token to automatically pull your code coverage data into the PostHog Data warehouse.

You can generate a personal API token under **Settings → Access** in your [Codecov account](https://app.codecov.io/). The token mirrors your own permissions on the git provider, so it can read every repository you can.

By default all of the owner's active repositories are synced; enter a comma-separated list of repository names to limit the import.
""",
            iconPath="/static/services/codecov.png",
            docsUrl="https://posthog.com/docs/cdp/sources/codecov",
            keywords=["coverage", "code coverage", "sentry"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="service",
                        label="Git provider",
                        required=True,
                        defaultValue="github",
                        options=[
                            SourceFieldSelectConfigOption(label="GitHub", value="github"),
                            SourceFieldSelectConfigOption(label="GitLab", value="gitlab"),
                            SourceFieldSelectConfigOption(label="Bitbucket", value="bitbucket"),
                            SourceFieldSelectConfigOption(label="GitHub Enterprise", value="github_enterprise"),
                            SourceFieldSelectConfigOption(label="GitLab Enterprise", value="gitlab_enterprise"),
                            SourceFieldSelectConfigOption(label="Bitbucket Server", value="bitbucket_server"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="owner_username",
                        label="Owner username",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-org",
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
                    SourceFieldInputConfig(
                        name="repositories",
                        label="Repositories (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="repo-one, repo-two",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.codecov.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.codecov.io": "Your Codecov API token is invalid or has been revoked. Generate a new token under Settings → Access in your Codecov account, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.codecov.io": "Your Codecov API token does not have access to this data. Check your permissions on the git provider, then reconnect.",
            "404 Client Error: Not Found for url: https://api.codecov.io": "Codecov could not find the configured owner. Check the git provider and owner username, then reconnect.",
        }

    def get_schemas(
        self,
        config: CodecovSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Incremental syncs re-pull boundary rows (a whole page for commits, the boundary
        # interval for the coverage trend); only merge dedupes those on the primary key, so
        # append mode stays off.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=_ENDPOINT_DESCRIPTIONS.get(endpoint),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: CodecovSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        is_valid, status_code = validate_codecov_credentials(config.api_token, config.service, config.owner_username)
        if is_valid:
            return True, None
        if status_code == 401:
            return False, "Invalid Codecov API token"
        if status_code == 404:
            return False, f"Owner '{config.owner_username}' not found on Codecov for the selected git provider"
        return False, "Could not connect to Codecov with the provided credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CodecovResumeConfig]:
        return ResumableSourceManager[CodecovResumeConfig](inputs, CodecovResumeConfig)

    def source_for_pipeline(
        self,
        config: CodecovSourceConfig,
        resumable_source_manager: ResumableSourceManager[CodecovResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return codecov_source(
            api_token=config.api_token,
            service=config.service,
            owner_username=config.owner_username,
            repositories=config.repositories,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
