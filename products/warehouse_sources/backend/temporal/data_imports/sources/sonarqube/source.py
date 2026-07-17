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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SonarqubeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sonarqube.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SONARQUBE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sonarqube.sonarqube import (
    SonarqubeResumeConfig,
    hostname_of,
    sonarqube_source,
    validate_credentials as validate_sonarqube_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SonarqubeSource(ResumableSource[SonarqubeSourceConfig, SonarqubeResumeConfig], ValidateDatabaseHostMixin):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SONARQUBE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SONARQUBE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Sonar (SonarSource) - SonarQube Server",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Connect your self-hosted SonarQube Server to pull code-quality data into the PostHog Data warehouse.

Enter your server URL (e.g. `https://sonarqube.yourcompany.com`) and a user token. Create a token under **My Account → Security → Generate Tokens** in your SonarQube instance. The token inherits your permissions, so it can read the projects, issues, and rules you can see. Syncing the **users** table additionally requires the *Administer System* permission.""",
            iconPath="/static/services/sonarqube.png",
            docsUrl="https://posthog.com/docs/cdp/sources/sonarqube",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Server URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://sonarqube.yourcompany.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="token",
                        label="User token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.sonarqube.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
            # Retrying can never fix a credential/permission problem, so fail the sync. Match the
            # stable status text, not the per-request URL.
            "401 Client Error: Unauthorized": "Your SonarQube token is invalid or has expired. Generate a new token in your SonarQube account settings, then reconnect.",
            "403 Client Error: Forbidden": "Your SonarQube token is missing the permissions needed to sync this data (the users table needs the Administer System permission). Check the token's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: SonarqubeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = SONARQUBE_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: SonarqubeSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            host_valid, host_error = self.is_database_host_valid(hostname_of(config.host), team_id)
        except ValueError as e:
            return False, str(e)
        if not host_valid:
            return False, host_error

        ok, status_code = validate_sonarqube_credentials(config.host, config.token)
        if ok:
            return True, None
        if status_code == 401:
            return False, "Invalid SonarQube token"
        return False, "Could not connect to SonarQube with the provided server URL and token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SonarqubeResumeConfig]:
        return ResumableSourceManager[SonarqubeResumeConfig](inputs, SonarqubeResumeConfig)

    def source_for_pipeline(
        self,
        config: SonarqubeSourceConfig,
        resumable_source_manager: ResumableSourceManager[SonarqubeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        host_valid, host_error = self.is_database_host_valid(hostname_of(config.host), inputs.team_id)
        if not host_valid:
            raise ValueError(host_error or "Invalid SonarQube host")

        return sonarqube_source(
            host=config.host,
            token=config.token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
