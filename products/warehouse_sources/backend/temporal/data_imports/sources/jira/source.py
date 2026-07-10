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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import JiraSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.jira.jira import (
    JiraResumeConfig,
    jira_source,
    validate_credentials as validate_jira_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jira.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    JIRA_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class JiraSource(ResumableSource[JiraSourceConfig, JiraResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("3",)
    default_version = "3"
    api_docs_url = "https://developer.atlassian.com/cloud/jira/platform/rest/v3/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.JIRA

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored API token is sent to `https://{subdomain}.atlassian.net`, so retargeting
        # `subdomain` must force the editor to re-enter the token (prevents credential exfiltration).
        return ["subdomain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.JIRA,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Jira",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Atlassian Jira credentials to pull your Jira data into the PostHog Data warehouse.

Create an API token at [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens).

The token authenticates as your Atlassian account, so the data we can sync is limited to the projects and issues that account can see.""",
            iconPath="/static/services/jira.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/jira",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="your-domain (from your-domain.atlassian.net)",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="email",
                        label="Email",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=True,
                        placeholder="you@example.com",
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
        config: JiraSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=JIRA_ENDPOINTS[endpoint].supports_incremental,
                supports_append=JIRA_ENDPOINTS[endpoint].supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: JiraSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        ok, status_code = validate_jira_credentials(config.subdomain, config.email, config.api_token)
        if ok:
            return True, None

        if status_code == 403 and schema_name is None:
            # Valid token, but missing scope for the probe endpoint — accept at source-create.
            return True, None

        if status_code == 401:
            return False, "Invalid Jira credentials. Check your email and API token."

        return False, "Could not connect to Jira. Check your subdomain, email, and API token."

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.jira.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Your Jira credentials are invalid or expired. Reconnect with a new API token.",
            "403 Client Error: Forbidden": "Your Jira account does not have permission to access this resource.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[JiraResumeConfig]:
        return ResumableSourceManager[JiraResumeConfig](inputs, JiraResumeConfig)

    def source_for_pipeline(
        self,
        config: JiraSourceConfig,
        resumable_source_manager: ResumableSourceManager[JiraResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return jira_source(
            subdomain=config.subdomain,
            email=config.email,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
