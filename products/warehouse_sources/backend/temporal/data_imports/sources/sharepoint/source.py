from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sharepoint import (
    SharePointSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sharepoint.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SHAREPOINT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sharepoint.sharepoint import (
    INVALID_SITE_URL_ERROR,
    SITES_DENIED_ERROR,
    SharePointResumeConfig,
    sharepoint_source,
    validate_credentials as validate_sharepoint_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SharePointSource(ResumableSource[SharePointSourceConfig, SharePointResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # `v1.0` is Microsoft Graph's only GA channel; `beta` is preview and not for production use.
    supported_versions = ("v1.0",)
    default_version = "v1.0"
    api_docs_url = "https://learn.microsoft.com/en-us/graph/versioning-and-support"

    @property
    def connection_host_fields(self) -> list[str]:
        # `tenant_id` selects which Entra directory the client secret is sent to. Without it here,
        # an editor could repoint a preserved secret at another tenant of a multi-tenant app.
        return ["tenant_id"]

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SHAREPOINT

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            INVALID_SITE_URL_ERROR: None,
            "400 Client Error: Bad Request for url: https://login.microsoftonline.com": (
                "Entra ID rejected the app registration. Check the tenant ID, application (client) ID, "
                "and client secret."
            ),
            "401 Client Error: Unauthorized for url: https://login.microsoftonline.com": (
                "Entra ID rejected the app credentials. Generate a new client secret and reconnect."
            ),
            "401 Client Error: Unauthorized for url: https://graph.microsoft.com": SITES_DENIED_ERROR,
            "403 Client Error: Forbidden for url: https://graph.microsoft.com": SITES_DENIED_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.sharepoint.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SharePointSourceConfig,
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
            descriptions={name: endpoint.description for name, endpoint in SHAREPOINT_ENDPOINTS.items()},
        )

    def validate_credentials(
        self,
        config: SharePointSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_sharepoint_credentials(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            site_urls=config.site_urls,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SharePointResumeConfig]:
        return ResumableSourceManager[SharePointResumeConfig](inputs, SharePointResumeConfig).with_namespace(
            inputs.schema_name
        )

    def source_for_pipeline(
        self,
        config: SharePointSourceConfig,
        resumable_source_manager: ResumableSourceManager[SharePointResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return sharepoint_source(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            site_urls=config.site_urls,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SHAREPOINT,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            label="SharePoint",
            keywords=["microsoft", "sharepoint online", "office 365", "microsoft 365"],
            caption=(
                "Sync SharePoint Online sites, lists and list items, document libraries, and file metadata "
                "through Microsoft Graph.\n\n"
                "Create an Entra ID app registration and add a client secret. Grant it the **Sites.Read.All** "
                "Microsoft Graph application permission and give admin consent. To limit access to a few "
                "sites, grant **Sites.Selected** instead and list those site URLs below. Then enter the "
                "directory (tenant) ID, application (client) ID, and client secret.\n\n"
                "Personal OneDrive sites are not synced."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/sharepoint",
            iconPath="/static/services/sharepoint.png",
            releaseStatus=ReleaseStatus.ALPHA,
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
                    SourceFieldInputConfig(
                        name="site_urls",
                        label="Site URLs (optional)",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=False,
                        placeholder="https://contoso.sharepoint.com/sites/marketing",
                        caption="One site URL per line. Leave empty to sync every site the app can read.",
                        secret=False,
                    ),
                ],
            ),
        )
