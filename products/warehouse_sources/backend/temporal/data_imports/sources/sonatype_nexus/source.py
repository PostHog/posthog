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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SonatypeNexusSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sonatype_nexus.settings import (
    ENDPOINTS,
    SONATYPE_NEXUS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sonatype_nexus.sonatype_nexus import (
    SonatypeNexusResumeConfig,
    hostname_of,
    sonatype_nexus_source,
    validate_credentials as validate_sonatype_nexus_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SonatypeNexusSource(
    ResumableSource[SonatypeNexusSourceConfig, SonatypeNexusResumeConfig], ValidateDatabaseHostMixin
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SONATYPENEXUS

    @property
    def connection_host_fields(self) -> list[str]:
        # `host` determines where the stored credentials are sent, so retargeting it
        # must re-require them.
        return ["host"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SONATYPE_NEXUS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Sonatype (Nexus Repository)",
            caption="""Connect your Sonatype Nexus Repository instance to pull your artifact inventory into the PostHog Data warehouse.

Enter your instance URL (e.g. `https://nexus.example.com`) and the username and password of a user with read access to the repositories you want to sync. A [user token](https://help.sonatype.com/en/user-tokens.html) also works: use the token name code as the username and the pass code as the password.

The tasks table additionally requires the `nx-tasks-read` privilege; deselect it if your user doesn't have it.""",
            iconPath="/static/services/sonatype_nexus.png",
            docsUrl="https://posthog.com/docs/cdp/sources/sonatype-nexus",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://nexus.example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="username",
                        label="Username",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="password",
                        label="Password",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.sonatype_nexus.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your Nexus credentials are invalid or have been revoked. Check the username and password (or user token) and reconnect.",
            "403 Client Error: Forbidden for url": "Your Nexus user does not have access to this resource. The tasks table requires the nx-tasks-read privilege, and repository content requires browse/read access — deselect the affected tables or use a user with the required privileges.",
        }

    def get_schemas(
        self,
        config: SonatypeNexusSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # The Nexus REST API exposes no server-side timestamp filter, so every
        # table is full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                detected_primary_keys=list(SONATYPE_NEXUS_ENDPOINTS[endpoint].primary_keys),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: SonatypeNexusSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            host_valid, host_error = self.is_database_host_valid(hostname_of(config.host), team_id)
        except ValueError:
            return False, "Invalid Nexus instance URL"
        if not host_valid:
            return False, host_error

        if validate_sonatype_nexus_credentials(config.host, config.username, config.password):
            return True, None

        return False, "Invalid Nexus credentials. Check the instance URL, username, and password."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SonatypeNexusResumeConfig]:
        return ResumableSourceManager[SonatypeNexusResumeConfig](inputs, SonatypeNexusResumeConfig)

    def source_for_pipeline(
        self,
        config: SonatypeNexusSourceConfig,
        resumable_source_manager: ResumableSourceManager[SonatypeNexusResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        try:
            host_valid, host_error = self.is_database_host_valid(hostname_of(config.host), inputs.team_id)
        except ValueError:
            raise ValueError("Invalid Nexus instance URL")
        if not host_valid:
            raise ValueError(host_error or "Invalid Nexus host")

        return sonatype_nexus_source(
            host=config.host,
            username=config.username,
            password=config.password,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
