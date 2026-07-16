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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import InfisicalSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.infisical.infisical import (
    HOST_NOT_ALLOWED_ERROR,
    INVALID_CREDENTIALS_ERROR,
    InfisicalResumeConfig,
    infisical_source,
    validate_credentials as validate_infisical_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.infisical.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class InfisicalSource(ResumableSource[InfisicalSourceConfig, InfisicalResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INFISICAL

    @property
    def connection_host_fields(self) -> list[str]:
        # `base_url` is where the stored client secret is sent; retargeting it must re-require
        # the credentials.
        return ["base_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INFISICAL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Infisical",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Connect an Infisical machine identity to pull your organization's audit logs, projects, identities, and memberships into the PostHog Data warehouse. Secret values are never synced.

In Infisical, create a machine identity under **Organization settings > Access control > Identities**, add a **Universal Auth** method to it, and grant it read permissions for the data you want to sync (audit logs, projects, identities, and memberships). Note that audit log access is plan-gated on Infisical Cloud.

- **Base URL**: `https://app.infisical.com` (US cloud), `https://eu.infisical.com` (EU cloud), or your self-hosted URL.
- **Organization ID**: found in your Infisical URL after `/org/`, or in organization settings.
- **Client ID / Client secret**: from the identity's Universal Auth configuration.
""",
            iconPath="/static/services/infisical.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/infisical",
            keywords=["secrets", "security", "audit", "devops"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="base_url",
                        label="Base URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://app.infisical.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="organization_id",
                        label="Organization ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="00000000-0000-0000-0000-000000000000",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            INVALID_CREDENTIALS_ERROR: "Your Infisical machine identity credentials are invalid or have been revoked. Update the client ID and client secret, then try again.",
            "401 Client Error": "Your Infisical machine identity credentials were rejected. Update the client ID and client secret, then try again.",
            "403 Client Error": "Your Infisical machine identity lacks the required permissions. Grant it read access to the data you want to sync, then try again.",
            HOST_NOT_ALLOWED_ERROR: "The Infisical base URL is not allowed. Use your Infisical Cloud or self-hosted instance URL.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.infisical.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: InfisicalSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description="The first sync fetches your plan's full retained history"
                if endpoint == "audit_logs"
                else None,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: InfisicalSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_infisical_credentials(
            config.base_url,
            config.client_id,
            config.client_secret,
            config.organization_id,
            schema_name,
            team_id,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[InfisicalResumeConfig]:
        return ResumableSourceManager[InfisicalResumeConfig](inputs, InfisicalResumeConfig)

    def source_for_pipeline(
        self,
        config: InfisicalSourceConfig,
        resumable_source_manager: ResumableSourceManager[InfisicalResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return infisical_source(
            base_url=config.base_url,
            client_id=config.client_id,
            client_secret=config.client_secret,
            organization_id=config.organization_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
