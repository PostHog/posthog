from typing import cast

from requests import HTTPError

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_application_insights.azure_application_insights import (
    AzureApplicationInsightsClient,
    AzureApplicationInsightsResumeConfig,
    azure_application_insights_source,
    validate_config,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_application_insights.settings import (
    API_DOCS_URL,
    AUTH_DOCS_URL,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
    OAuth2AuthRequestError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azureapplicationinsights import (
    AzureApplicationInsightsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

AUTH_ERROR = "Azure authentication failed. Check the tenant ID, client ID, and client secret."
PERMISSION_ERROR = "Grant your Microsoft Entra app the Reader role on this Application Insights resource."
APP_ERROR = "Application Insights could not find the resource. Check the application ID and its access permissions."


@SourceRegistry.register
class AzureApplicationInsightsSource(
    ResumableSource[AzureApplicationInsightsSourceConfig, AzureApplicationInsightsResumeConfig]
):
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = API_DOCS_URL
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZUREAPPLICATIONINSIGHTS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": PERMISSION_ERROR,
            "404 Client Error": APP_ERROR,
            OAUTH2_PERMANENT_ERROR_MARKER: AUTH_ERROR,
            "Azure query returned incomplete results": "Azure returned incomplete results. Reduce the telemetry volume and try again.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.azure_application_insights.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AzureApplicationInsightsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=ENDPOINTS)

    def validate_credentials(
        self,
        config: AzureApplicationInsightsSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            validate_config(config)
        except ValueError as error:
            return False, str(error)
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, "Unknown Application Insights table."
        client = AzureApplicationInsightsClient(config, self.resolve_api_version(api_version), team_id, "")
        try:
            client.query(f"{schema_name} | take 1" if schema_name else "print 1", "PT1M")
        except OAuth2AuthRequestError as error:
            if error.is_permanent:
                return False, AUTH_ERROR
            raise
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 403 and schema_name is None:
                return True, None
            if status in (401, 403, 404):
                return False, {401: AUTH_ERROR, 403: PERMISSION_ERROR, 404: APP_ERROR}[status]
            raise
        return True, None

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[AzureApplicationInsightsResumeConfig]:
        return ResumableSourceManager(inputs, AzureApplicationInsightsResumeConfig)

    def source_for_pipeline(
        self,
        config: AzureApplicationInsightsSourceConfig,
        resumable_source_manager: ResumableSourceManager[AzureApplicationInsightsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return azure_application_insights_source(
            config=config,
            api_version=self.resolve_api_version(inputs.api_version),
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            manager=resumable_source_manager,
            last_value=inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZUREAPPLICATIONINSIGHTS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Azure (Application Insights)",
            iconPath="/static/services/azure_application_insights.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Use a Microsoft Entra app registration with the Reader role on your Application Insights resource. "
                "Create its client secret under **App registrations > Certificates & secrets**. "
                "Find the Application Insights application ID under **API Access**. "
                f"Follow [Microsoft's authentication setup]({AUTH_DOCS_URL}). "
                "Supports Azure public cloud. Each sync reads at most the last seven days. "
                "Incremental sync repeats the previous hour to capture delayed telemetry. "
                "Older telemetry requires a separate export."
            ),
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="tenant_id",
                        label="Tenant ID",
                        type=SourceFieldInputConfigType.TEXT,
                        secret=False,
                        required=True,
                        placeholder="00000000-0000-0000-0000-000000000000",
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        secret=False,
                        required=True,
                        placeholder="00000000-0000-0000-0000-000000000000",
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        secret=True,
                        required=True,
                        placeholder="",
                    ),
                    SourceFieldInputConfig(
                        name="application_id",
                        label="Application Insights application ID",
                        type=SourceFieldInputConfigType.TEXT,
                        secret=False,
                        required=True,
                        placeholder="00000000-0000-0000-0000-000000000000",
                    ),
                ],
            ),
        )
