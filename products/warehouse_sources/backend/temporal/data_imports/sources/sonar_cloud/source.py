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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SonarCloudSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    REGION_HOSTS,
    SONAR_CLOUD_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud.sonar_cloud import (
    SonarCloudResumeConfig,
    sonar_cloud_source,
    validate_credentials as validate_sonar_cloud_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SonarCloudSource(ResumableSource[SonarCloudSourceConfig, SonarCloudResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SONARCLOUD

    @property
    def connection_host_fields(self) -> list[str]:
        # Both dimensions retarget the preserved token: `region` decides which regional host it is
        # sent to, and `organization` decides which tenant it acts on. Changing either must re-require
        # the token so an editor can't silently redirect the stored credential to another host or org.
        return ["region", "organization"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SONAR_CLOUD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Sonar Cloud",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your SonarQube Cloud user token and organization key to sync code-quality data into the PostHog Data warehouse.

Generate a **user token** under **My Account → Security** in SonarQube Cloud, and find your **organization key** on your organization's homepage.
""",
            iconPath="/static/services/sonar_cloud.png",
            docsUrl="https://posthog.com/docs/cdp/sources/sonar-cloud",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="token",
                        label="User token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="organization",
                        label="Organization key",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-organization",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="eu",
                        options=[
                            SourceFieldSelectConfigOption(label="EU (sonarcloud.io)", value="eu"),
                            SourceFieldSelectConfigOption(label="US (sonarqube.us)", value="us"),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Match the stable status text + region host, not the per-request path/query. A bad token or a
        # missing scope can never be satisfied by retrying, so fail the sync fast.
        errors: dict[str, str | None] = {}
        for host in REGION_HOSTS.values():
            errors[f"401 Client Error: Unauthorized for url: {host}"] = (
                "Your SonarQube Cloud token is invalid or has been revoked. Generate a new user token and reconnect."
            )
            errors[f"403 Client Error: Forbidden for url: {host}"] = (
                "Your SonarQube Cloud token is missing the permissions needed to sync this data. "
                "Check the token's access and reconnect."
            )
        return errors

    def get_schemas(
        self,
        config: SonarCloudSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # SonarQube Cloud exposes no uniform server-side update cursor, so every stream is full refresh.
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=SONAR_CLOUD_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: SonarCloudSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        status = validate_sonar_cloud_credentials(config.token, config.organization, config.region)
        if status == 200:
            return True, None
        if status == 401:
            return False, "Invalid SonarQube Cloud token"
        # A 403 means the token is genuine but lacks scope for the probe endpoint. Accept it at
        # source-create — users may only grant scopes for the tables they want — but reject it when
        # validating a specific schema.
        if status == 403 and schema_name is None:
            return True, None
        if status == 403:
            return False, "Your SonarQube Cloud token does not have access to this resource"
        return False, "Could not connect to SonarQube Cloud. Check your token, organization key, and region."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SonarCloudResumeConfig]:
        return ResumableSourceManager[SonarCloudResumeConfig](inputs, SonarCloudResumeConfig)

    def source_for_pipeline(
        self,
        config: SonarCloudSourceConfig,
        resumable_source_manager: ResumableSourceManager[SonarCloudResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return sonar_cloud_source(
            token=config.token,
            organization=config.organization,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
