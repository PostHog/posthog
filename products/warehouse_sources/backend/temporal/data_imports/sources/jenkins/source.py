from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.cloud_utils import is_cloud

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import JenkinsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.jenkins.jenkins import (
    JenkinsResumeConfig,
    hostname_of,
    jenkins_source,
    scheme_of,
    validate_credentials as validate_jenkins_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jenkins.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class JenkinsSource(ResumableSource[JenkinsSourceConfig, JenkinsResumeConfig], ValidateDatabaseHostMixin):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.JENKINS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.JENKINS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            keywords=["ci", "cd", "continuous integration"],
            label="Jenkins",
            releaseStatus=ReleaseStatus.ALPHA,
            docsUrl="https://posthog.com/docs/cdp/sources/jenkins",
            caption="""Enter your Jenkins URL, username, and API token to sync your CI/CD data into the PostHog Data warehouse.

Jenkins is self-hosted, so enter the base URL of your own instance (for example `https://jenkins.example.com`).

Create an API token from your Jenkins user page under **Configure > API Token**. The account needs **Overall/Read** plus **Job/Read** permission on the jobs you want to sync.""",
            iconPath="/static/services/jenkins.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Jenkins URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://jenkins.example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="username",
                        label="Username",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="jenkins-user",
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

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.jenkins.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked token surfaces as a 401 when `_fetch` calls `raise_for_status()`.
            # Retrying can never satisfy a credential problem, so stop the sync.
            "401 Client Error: Unauthorized for url": "Your Jenkins username or API token is invalid or has been revoked. Create a new API token on your Jenkins user page, then reconnect.",
            # 403 at sync time means the account is missing Overall/Read or Job/Read on a synced job.
            "403 Client Error: Forbidden for url": "The Jenkins account is missing the read permission needed to sync this data. Grant Overall/Read and Job/Read, then reconnect.",
        }

    def get_schemas(
        self,
        config: JenkinsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        descriptions = {
            "jobs": "Every job in the instance, recursing into Folders and Multibranch Pipelines. Full refresh — jobs carry no creation timestamp to sync incrementally on.",
            "builds": "Per-job build history (number, result, duration, timestamp). Incrementally synced newest-first on the build start time; a build's result and duration won't update once it drops below the watermark.",
        }

        def _build_schema(endpoint: str) -> SourceSchema:
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=descriptions.get(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def _validate_host(self, host: str | None, team_id: int) -> tuple[bool, str | None]:
        try:
            host_valid, host_error = self.is_database_host_valid(hostname_of(host), team_id)
            scheme = scheme_of(host)
        except ValueError:
            return False, "Invalid Jenkins URL"
        if not host_valid:
            return False, host_error
        # On Cloud the API token would otherwise be sent in cleartext to a customer-supplied http://
        # host. Self-hosted PostHog may still reach a Jenkins instance over http on its own network.
        if is_cloud() and scheme != "https":
            return False, "Jenkins URL must use https"
        return True, None

    def validate_credentials(
        self,
        config: JenkinsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        host_valid, host_error = self._validate_host(config.host, team_id)
        if not host_valid:
            return False, host_error

        return validate_jenkins_credentials(config.host, config.username, config.api_token, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[JenkinsResumeConfig]:
        return ResumableSourceManager[JenkinsResumeConfig](inputs, JenkinsResumeConfig)

    def source_for_pipeline(
        self,
        config: JenkinsSourceConfig,
        resumable_source_manager: ResumableSourceManager[JenkinsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        host_valid, host_error = self._validate_host(config.host, inputs.team_id)
        if not host_valid:
            raise ValueError(host_error or "Invalid Jenkins URL")

        return jenkins_source(
            host=config.host,
            username=config.username,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
