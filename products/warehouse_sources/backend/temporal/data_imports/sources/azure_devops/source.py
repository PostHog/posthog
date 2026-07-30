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
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops import (
    AzureDevOpsResumeConfig,
    azure_devops_source,
    validate_credentials as validate_azure_devops_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AzureDevOpsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AzureDevOpsSource(ResumableSource[AzureDevOpsSourceConfig, AzureDevOpsResumeConfig]):
    api_docs_url = "https://learn.microsoft.com/en-us/rest/api/azure/devops"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZUREDEVOPS

    @property
    def connection_host_fields(self) -> list[str]:
        # The PAT is sent to dev.azure.com/<organization>, so retargeting the
        # organization must force re-entry of the token.
        return ["organization"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "the personal access token is invalid or expired": "Azure DevOps authentication failed. Please check your personal access token (it may have expired).",
            "401 Client Error: Unauthorized for url: https://dev.azure.com": "Azure DevOps authentication failed. Please check your personal access token.",
            "403 Client Error: Forbidden for url: https://dev.azure.com": "Azure DevOps denied access. Please check that your personal access token has read scopes for this data.",
            "404 Client Error: Not Found for url: https://dev.azure.com": "Azure DevOps organization not found. Please check the organization name.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AZURE_DEV_OPS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Azure DevOps",
            caption="""Enter your Azure DevOps credentials to pull your project, build, and work item data into the PostHog Data warehouse.

Your organization is the first path segment of your Azure DevOps URL — for `dev.azure.com/myorg` enter `myorg`. Create a personal access token under User settings > Personal access tokens with read scopes for the data you want to sync (Work Items, Code, Build, Project and Team).""",
            iconPath="/static/services/azure_devops.png",
            docsUrl="https://posthog.com/docs/cdp/sources/azure-devops",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="organization",
                        label="Organization",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="myorg",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="personal_access_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: AzureDevOpsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: AzureDevOpsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_azure_devops_credentials(config.organization, config.personal_access_token):
            return True, None

        return False, "Invalid Azure DevOps credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AzureDevOpsResumeConfig]:
        return ResumableSourceManager[AzureDevOpsResumeConfig](inputs, AzureDevOpsResumeConfig)

    def source_for_pipeline(
        self,
        config: AzureDevOpsSourceConfig,
        resumable_source_manager: ResumableSourceManager[AzureDevOpsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return azure_devops_source(
            organization=config.organization,
            personal_access_token=config.personal_access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
