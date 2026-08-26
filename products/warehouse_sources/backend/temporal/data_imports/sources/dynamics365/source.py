from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics365.dynamics365 import (
    INVALID_ORGANIZATION_URL_ERROR,
    INVALID_TENANT_ID_ERROR,
    INVALID_WATERMARK_ERROR,
    Dynamics365ConfigurationError,
    Dynamics365ResumeConfig,
    dynamics365_source,
    probe_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics365.settings import (
    DYNAMICS365_API_VERSION,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dynamics365 import (
    Dynamics365SourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

CREDENTIALS_REJECTED_ERROR = "Dynamics 365 rejected these credentials. Check the directory (tenant) ID, application (client) ID, and client secret, and that the secret hasn't expired."
PERMISSION_ERROR = "Dynamics 365 accepted the credentials but denied access to the data. Check that the app registration has an application user in the environment with a security role that can read this table."
TABLE_MISSING_ERROR = "This table doesn't exist in your Dynamics 365 environment. It belongs to an app (Sales, Customer Service, Marketing) that isn't installed there."
UNREACHABLE_ERROR = "Couldn't reach your Dynamics 365 environment. Check the environment URL and try again."


@SourceRegistry.register
class Dynamics365Source(ResumableSource[Dynamics365SourceConfig, Dynamics365ResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = (DYNAMICS365_API_VERSION,)
    default_version = DYNAMICS365_API_VERSION
    api_docs_url = "https://learn.microsoft.com/en-us/power-apps/developer/data-platform/webapi/overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DYNAMICS365

    @property
    def connection_host_fields(self) -> list[str]:
        # The client secret is posted to a token endpoint derived from `tenant_id`, and the minted
        # token is sent to `organization_url` — retargeting either must re-require the secret.
        return ["organization_url", "tenant_id"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            OAUTH2_PERMANENT_ERROR_MARKER: CREDENTIALS_REJECTED_ERROR,
            "401 Client Error: Unauthorized for url": CREDENTIALS_REJECTED_ERROR,
            "403 Client Error: Forbidden for url": PERMISSION_ERROR,
            "404 Client Error: Not Found for url": TABLE_MISSING_ERROR,
            INVALID_ORGANIZATION_URL_ERROR: None,
            INVALID_TENANT_ID_ERROR: None,
            INVALID_WATERMARK_ERROR: None,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics365.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: Dynamics365SourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: Dynamics365SourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            is_valid, status = probe_credentials(
                config.organization_url,
                config.tenant_id,
                config.client_id,
                config.client_secret,
                self.resolve_api_version(api_version),
                schema_name,
                # A 403 at source-create means the token minted but the application user can't read
                # accounts — the credentials are genuine, so let setup continue. The per-schema
                # check (schema_name set) still fails on 403 so the user sees which table needs a
                # grant before syncing it.
                ok_statuses=(200,) if schema_name else (200, 403),
            )
        except Dynamics365ConfigurationError as error:
            return False, str(error)

        if is_valid:
            return True, None
        if status == 401:
            return False, CREDENTIALS_REJECTED_ERROR
        if status == 403:
            return False, PERMISSION_ERROR
        if status == 404:
            return False, TABLE_MISSING_ERROR
        return False, UNREACHABLE_ERROR

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[Dynamics365ResumeConfig]:
        return ResumableSourceManager[Dynamics365ResumeConfig](inputs, Dynamics365ResumeConfig)

    def source_for_pipeline(
        self,
        config: Dynamics365SourceConfig,
        resumable_source_manager: ResumableSourceManager[Dynamics365ResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return dynamics365_source(
            organization_url=config.organization_url,
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DYNAMICS365,
            category=DataWarehouseSourceCategory.CRM,
            keywords=["microsoft dynamics", "dynamics", "dataverse"],
            label="Microsoft Dynamics 365",
            caption="""Sync your Dynamics 365 (Dataverse) customer data — accounts, contacts, leads, opportunities, cases and activities — into the PostHog Data warehouse.

To connect, register an app in **Microsoft Entra ID** and add a client secret. Then add that app as an **application user** in your Dynamics 365 environment (Power Platform admin center > Environments > Settings > Users + permissions > Application users) and give it a security role that can read the tables you want to sync. The environment URL is the one you use to open the app, for example `https://contoso.crm.dynamics.com`.""",
            iconPath="/static/services/dynamics365.png",
            docsUrl="https://posthog.com/docs/cdp/sources/dynamics365",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="organization_url",
                        label="Environment URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://contoso.crm.dynamics.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="tenant_id",
                        label="Directory (tenant) ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="72f988bf-86f1-41af-91ab-2d7cd011db47",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Application (client) ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="00001111-aaaa-2222-bbbb-3333cccc4444",
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
