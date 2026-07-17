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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PulumiCloudSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pulumi_cloud.pulumi_cloud import (
    PulumiCloudResumeConfig,
    pulumi_cloud_source,
    validate_credentials as validate_pulumi_cloud_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pulumi_cloud.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PULUMI_CLOUD_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PulumiCloudSource(ResumableSource[PulumiCloudSourceConfig, PulumiCloudResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PULUMICLOUD

    @property
    def connection_host_fields(self) -> list[str]:
        # `organization` selects which Pulumi tenant the stored token queries, so retargeting it
        # must re-require the token — otherwise a preserved credential could be aimed at another
        # organization the token can access without the editor knowing the redacted secret.
        return ["organization"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PULUMI_CLOUD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Pulumi",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Pulumi Cloud access token and organization name to pull your infrastructure-as-code data into the PostHog Data warehouse.

Create a personal access token from your [Pulumi Cloud access tokens page](https://app.pulumi.com/account/tokens), or an organization access token from your organization's settings. The token inherits its owner's access, so no extra scopes are required.

The organization name is the one shown in your Pulumi Cloud console URL (`app.pulumi.com/<organization>`). Audit logs additionally require a Pulumi Cloud plan with audit logs enabled.""",
            iconPath="/static/services/pulumi_cloud.png",
            docsUrl="https://posthog.com/docs/cdp/sources/pulumi-cloud",
            keywords=["iac", "infrastructure as code", "deployments", "devops"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="pul-...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="organization",
                        label="Organization",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-org",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.pulumi_cloud.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.pulumi.com": "Your Pulumi Cloud access token is invalid or has been revoked. Create a new access token in Pulumi Cloud, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.pulumi.com": "Your Pulumi Cloud access token does not have access to this data. Check the token's organization membership (audit logs also require a plan with audit logs enabled), then reconnect.",
        }

    def get_schemas(
        self,
        config: PulumiCloudSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = PULUMI_CLOUD_ENDPOINTS[endpoint]
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                # Incremental runs re-pull a trailing safety window that merge dedupes on the
                # primary key; append would materialize those re-pulled rows as duplicates.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=endpoint_config.description,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: PulumiCloudSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_pulumi_cloud_credentials(config.access_token):
            return True, None

        return False, "Invalid Pulumi Cloud access token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PulumiCloudResumeConfig]:
        return ResumableSourceManager[PulumiCloudResumeConfig](inputs, PulumiCloudResumeConfig)

    def source_for_pipeline(
        self,
        config: PulumiCloudSourceConfig,
        resumable_source_manager: ResumableSourceManager[PulumiCloudResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return pulumi_cloud_source(
            access_token=config.access_token,
            organization=config.organization,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
