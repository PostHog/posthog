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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.microsoftentraid import (
    MicrosoftEntraIdSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_entra_id.microsoft_entra_id import (
    GRAPH_HOST,
    MicrosoftEntraIdResumeConfig,
    check_endpoint_permissions,
    microsoft_entra_id_source,
    validate_credentials as validate_entra_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_entra_id.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SHOULD_SYNC_DEFAULT,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

CAPTION = """Sync your Microsoft Entra ID (Azure AD) directory into the PostHog Data warehouse through the Microsoft Graph API.

1. In the [Microsoft Entra admin center](https://entra.microsoft.com), register an application and copy its **Directory (tenant) ID** and **Application (client) ID**.
2. Under **Certificates & secrets**, create a client secret and copy the value straight away. Microsoft only shows it once.
3. Under **API permissions**, add the Microsoft Graph **application** permissions for the tables you want and grant admin consent: `User.Read.All`, `Group.Read.All`, `GroupMember.Read.All`, `Application.Read.All`, `Device.Read.All`, `RoleManagement.Read.Directory`, `Organization.Read.All`, and `AuditLog.Read.All` for the audit and sign-in logs.

Sign-in logs also need a Microsoft Entra ID P1 or P2 license, so that table starts switched off."""


@SourceRegistry.register
class MicrosoftEntraIdSource(ResumableSource[MicrosoftEntraIdSourceConfig, MicrosoftEntraIdResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Graph exposes exactly two versions, `v1.0` (what this source calls) and `beta`.
    supported_versions = ("v1.0",)
    default_version = "v1.0"
    api_docs_url = "https://learn.microsoft.com/en-us/graph/api/overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTENTRAID

    @property
    def connection_host_fields(self) -> list[str]:
        # The client secret is posted to the tenant-scoped token endpoint, so repointing the tenant
        # must force the editor to re-enter it rather than replaying it against another directory.
        return ["tenant_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MICROSOFT_ENTRA_ID,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Entra ID",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["azure ad", "azure active directory", "entra", "aad", "microsoft graph"],
            caption=CAPTION,
            iconPath="/static/services/microsoft_entra_id.png",
            docsUrl="https://posthog.com/docs/cdp/sources/microsoft-entra-id",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="tenant_id",
                        label="Directory (tenant) ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="00000000-0000-0000-0000-000000000000",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Application (client) ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="00000000-0000-0000-0000-000000000000",
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
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_entra_id.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            f"401 Client Error: Unauthorized for url: https://{GRAPH_HOST}": "Microsoft Graph rejected the access token. Check that the client secret has not expired, then reconnect.",
            f"403 Client Error: Forbidden for url: https://{GRAPH_HOST}": "The app registration is missing an admin-consented Microsoft Graph application permission for this table. Grant it in the Microsoft Entra admin center, then retry.",
            # Every permanent token-exchange failure (invalid_client, invalid_grant,
            # unauthorized_client, invalid_scope, a misconfigured token endpoint) carries this
            # marker; the transient 429/5xx token errors do not.
            OAUTH2_PERMANENT_ERROR_MARKER: "Microsoft Entra ID rejected the app credentials. Check the directory (tenant) ID, application (client) ID and client secret, then reconnect.",
        }

    def get_schemas(
        self,
        config: MicrosoftEntraIdSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            should_sync_default=SHOULD_SYNC_DEFAULT,
        )

    def validate_credentials(
        self,
        config: MicrosoftEntraIdSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_entra_credentials(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            schema_name=schema_name,
            api_version=self.resolve_api_version(api_version),
        )

    def get_endpoint_permissions(
        self,
        config: MicrosoftEntraIdSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        return check_endpoint_permissions(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            endpoints=endpoints,
            api_version=self.resolve_api_version(api_version),
        )

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[MicrosoftEntraIdResumeConfig]:
        return ResumableSourceManager[MicrosoftEntraIdResumeConfig](inputs, MicrosoftEntraIdResumeConfig)

    def source_for_pipeline(
        self,
        config: MicrosoftEntraIdSourceConfig,
        resumable_source_manager: ResumableSourceManager[MicrosoftEntraIdResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return microsoft_entra_id_source(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            api_version=self.resolve_api_version(inputs.api_version),
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
