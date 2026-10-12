from typing import Optional, cast

import structlog

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSwitchGroupConfig,
)
from products.warehouse_sources.backend.models.external_data_schema import SCHEMA_RESOURCE_ID_METADATA_KEY
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.excel_parsing import EXCEL_ERROR
from products.warehouse_sources.backend.temporal.data_imports.sources.common.file_parsing import FORMAT_ERROR
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.sharepoint._config import SharePointSourceConfig
from sources.sharepoint.files import (
    SharePointFilePatternError,
    compile_file_pattern,
    discover_file_tables,
    sharepoint_file_source,
)
from sources.sharepoint.settings import (
    ENDPOINTS,
    FILE_NOT_FOUND_ERROR,
    INCREMENTAL_FIELDS,
    PATTERN_ERROR,
    SHAREPOINT_ENDPOINTS,
)
from sources.sharepoint.sharepoint import (
    INVALID_SITE_URL_ERROR,
    SITES_DENIED_ERROR,
    SharePointClient,
    SharePointResumeConfig,
    SharePointSiteURLError,
    parse_site_urls,
    sharepoint_source,
    validate_credentials as validate_sharepoint_credentials,
)


@SourceRegistry.register
class SharePointSource(ResumableSource[SharePointSourceConfig, SharePointResumeConfig]):
    lists_tables_without_credentials = True  # Placeholder configs leave file import off and need no network access.
    # A renamed or moved file keeps its drive item id.
    uses_stable_schema_resource_ids = True
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
            FILE_NOT_FOUND_ERROR: "The SharePoint file is missing. Refresh the source's tables or restore the file.",
            FORMAT_ERROR: (
                "PostHog could not read the file format. Use a CSV, TSV, or XLSX file and refresh the source's tables."
            ),
            EXCEL_ERROR: (
                "PostHog could not read the Excel worksheet. Check that the worksheet exists and the file is under 100 MB. "
                "Save it as .xlsx again, then refresh the source's tables."
            ),
            PATTERN_ERROR: "The file pattern is not a valid regular expression. Fix the pattern and try again.",
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
        from sources.sharepoint.canonical_descriptions import CANONICAL_DESCRIPTIONS

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
        schemas = build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            descriptions={name: endpoint.description for name, endpoint in SHAREPOINT_ENDPOINTS.items()},
        )
        import_files = config.import_files
        if (
            import_files is not None
            and import_files.enabled
            and not (names is not None and all(name in ENDPOINTS for name in names))
        ):
            logger = structlog.get_logger(__name__)
            client = SharePointClient(config.tenant_id, config.client_id, config.client_secret, logger)
            tables = discover_file_tables(client, config.site_urls, import_files.file_pattern, logger)
            schemas.extend(
                SourceSchema(
                    name=name,
                    supports_incremental=False,
                    supports_append=False,
                    label=file.label,
                    description=file.description,
                    schema_metadata={SCHEMA_RESOURCE_ID_METADATA_KEY: file.resource_id},
                )
                for name, file in tables.items()
            )
        if names is not None:
            requested = set(names)
            schemas = [schema for schema in schemas if schema.name in requested]
        return schemas

    def validate_credentials(
        self,
        config: SharePointSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        import_files = config.import_files
        if import_files is not None and import_files.enabled:
            try:
                if not parse_site_urls(config.site_urls):
                    return False, "Enter at least one site URL to import file contents."
                compile_file_pattern(import_files.file_pattern)
            except (SharePointSiteURLError, SharePointFilePatternError) as error:
                return False, str(error)
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
        if inputs.schema_name not in ENDPOINTS:
            resource_id = (inputs.schema_metadata or {}).get(SCHEMA_RESOURCE_ID_METADATA_KEY)
            return sharepoint_file_source(
                SharePointClient(config.tenant_id, config.client_id, config.client_secret, inputs.logger),
                inputs.schema_name,
                resource_id if isinstance(resource_id, str) else None,
                inputs.logger,
            )
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
                "through Microsoft Graph. You can also import CSV and Excel file contents as separate tables.\n\n"
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
                    SourceFieldSwitchGroupConfig(
                        name="import_files",
                        label="Import CSV and Excel file contents?",
                        default=False,
                        caption=(
                            "Turn this on to create one table for each CSV file and each Excel worksheet "
                            "in the document libraries of the sites above. Each sync reads the files in full. "
                            "Excel files over 100 MB are skipped. Site URLs are required when this is on."
                        ),
                        fields=cast(
                            list[FieldType],
                            [
                                SourceFieldInputConfig(
                                    name="file_pattern",
                                    label="File pattern (optional)",
                                    type=SourceFieldInputConfigType.TEXT,
                                    required=False,
                                    placeholder=r"^Shared Documents/reports/",
                                    caption=(
                                        "A regular expression matched against each file's path, which starts with the "
                                        "document library name. Leave it empty to import every CSV and Excel file."
                                    ),
                                    secret=False,
                                ),
                            ],
                        ),
                    ),
                ],
            ),
        )
