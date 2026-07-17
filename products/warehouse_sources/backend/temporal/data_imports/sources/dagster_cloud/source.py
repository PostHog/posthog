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
from products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.dagster_cloud import (
    DagsterCloudResumeConfig,
    dagster_cloud_source,
    validate_credentials as validate_dagster_cloud_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.settings import (
    DAGSTER_CLOUD_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DagsterCloudSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DagsterCloudSource(ResumableSource[DagsterCloudSourceConfig, DagsterCloudResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DAGSTERCLOUD

    @property
    def connection_host_fields(self) -> list[str]:
        # Both fields determine the `*.dagster.cloud` URL the stored API token is sent to, so
        # changing either must force the editor to re-enter the token.
        return ["organization", "deployment"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DAGSTER_CLOUD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Dagster+ (Dagster Cloud)",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Connect your Dagster+ deployment to sync run history, backfills, and your asset catalog into the PostHog Data warehouse.

Create a user token under **Organization settings → Tokens** in Dagster+, then enter your organization name, deployment name, and the token below.""",
            iconPath="/static/services/dagster_cloud.png",
            docsUrl="https://posthog.com/docs/cdp/sources/dagster-cloud",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="organization",
                        label="Organization",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="your-org",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="deployment",
                        label="Deployment",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="prod",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="user:...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Dagster+ API token is invalid or has been revoked. Create a new user token in your organization settings, then reconnect.",
            "403 Client Error": "Your Dagster+ API token cannot access this deployment. Check the token's permissions and the organization/deployment names, then reconnect.",
        }

    def get_schemas(
        self,
        config: DagsterCloudSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=DAGSTER_CLOUD_ENDPOINTS[endpoint].supports_incremental,
                # Runs mutate after creation (status advances), so append-only would materialize
                # duplicate rows per run — merge on the primary key is the only correct mode.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=DAGSTER_CLOUD_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: DagsterCloudSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_dagster_cloud_credentials(config.organization, config.deployment, config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DagsterCloudResumeConfig]:
        return ResumableSourceManager[DagsterCloudResumeConfig](inputs, DagsterCloudResumeConfig)

    def source_for_pipeline(
        self,
        config: DagsterCloudSourceConfig,
        resumable_source_manager: ResumableSourceManager[DagsterCloudResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return dagster_cloud_source(
            organization=config.organization,
            deployment=config.deployment,
            api_token=config.api_token,
            endpoint_name=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
