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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.deepsource.deepsource import (
    DeepsourceResumeConfig,
    deepsource_source,
    validate_credentials as validate_deepsource_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deepsource.settings import (
    DEEPSOURCE_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DeepsourceSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

_ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    "repositories": "All repositories in the account, including ones not activated on DeepSource",
    "analysis_runs": "One row per analysis run with its status and occurrence summary",
    "issues": "Currently open issue types per repository with category, severity, and occurrence count",
    "issue_occurrences": "Every open occurrence of an issue with its file path and position",
    "vulnerability_occurrences": "Dependency vulnerabilities (SCA) with CVSS/EPSS scores per repository",
    "metrics": "Latest value per code-quality metric and language (coverage, duplication, and more)",
    "reports": "Current value and status of each compliance and trend report (OWASP Top 10, code health, and more)",
}


@SourceRegistry.register
class DeepsourceSource(ResumableSource[DeepsourceSourceConfig, DeepsourceResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DEEPSOURCE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DEEPSOURCE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="DeepSource",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Import your DeepSource static-analysis data — repositories, analysis runs, issues, code-quality metrics, and reports — into the PostHog Data warehouse.

Generate a personal access token from the **Tokens** tab in your [DeepSource user settings](https://app.deepsource.com/). The token is scoped to your account, so it can read every account and repository you have access to.

The account login is the organization or user name exactly as it appears in DeepSource (for a GitHub organization, this is the organization's login).
""",
            iconPath="/static/services/deepsource.png",
            docsUrl="https://posthog.com/docs/cdp/sources/deepsource",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="account_login",
                        label="Account login",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-organization",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="vcs_provider",
                        label="VCS provider",
                        required=True,
                        defaultValue="GITHUB",
                        options=[
                            SourceFieldSelectConfigOption(label="GitHub", value="GITHUB"),
                            SourceFieldSelectConfigOption(label="GitLab", value="GITLAB"),
                            SourceFieldSelectConfigOption(label="Bitbucket", value="BITBUCKET"),
                            SourceFieldSelectConfigOption(label="GitHub Enterprise", value="GITHUB_ENTERPRISE"),
                            SourceFieldSelectConfigOption(label="Bitbucket Data Center", value="BITBUCKET_DATACENTER"),
                            SourceFieldSelectConfigOption(label="Azure DevOps Services", value="ADS"),
                            SourceFieldSelectConfigOption(label="Google Source Repositories", value="GSR"),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.deepsource.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked PAT surfaces as a 401/403 raised from the GraphQL transport.
            # Match the stable status text plus the fixed API host, never the variable detail.
            "401 Client Error: Unauthorized for url: https://api.deepsource.com": "Your DeepSource personal access token is invalid or has been revoked. Generate a new token in your DeepSource user settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.deepsource.com": "Your DeepSource personal access token does not have access to this data. Check the token's account access, then reconnect.",
            # A wrong account login / VCS provider resolves the account to null — retrying can
            # never fix the configuration.
            "DeepSource account not found": "The configured DeepSource account could not be found. Check the account login and VCS provider, and that your token has access to it.",
        }

    def get_schemas(
        self,
        config: DeepsourceSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # No DeepSource connection accepts a server-side timestamp filter (Relay cursor args
        # only), so every schema is full refresh — see settings.py.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                should_sync_default=DEEPSOURCE_ENDPOINTS[endpoint].should_sync_default,
                description=_ENDPOINT_DESCRIPTIONS.get(endpoint),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: DeepsourceSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_deepsource_credentials(config.api_token, config.account_login, config.vcs_provider)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DeepsourceResumeConfig]:
        return ResumableSourceManager[DeepsourceResumeConfig](inputs, DeepsourceResumeConfig)

    def source_for_pipeline(
        self,
        config: DeepsourceSourceConfig,
        resumable_source_manager: ResumableSourceManager[DeepsourceResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return deepsource_source(
            api_token=config.api_token,
            account_login=config.account_login,
            vcs_provider=config.vcs_provider,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
