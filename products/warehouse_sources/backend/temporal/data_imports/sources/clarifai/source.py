from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clarifai.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clarifai.clarifai import (
    ClarifaiClient,
    ClarifaiResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clarifai.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    HOST_ERROR,
    PERMISSION_ERROR,
    RESOURCE_ERROR,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clarifai import (
    ClarifaiSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ClarifaiSource(ResumableSource[ClarifaiSourceConfig, ClarifaiResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://docs.clarifai.com/resources/api-overview/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLARIFAI

    @property
    def connection_host_fields(self) -> list[str]:
        return ["api_host"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": PERMISSION_ERROR,
            "404 Client Error": RESOURCE_ERROR,
            AUTH_ERROR: AUTH_ERROR,
            PERMISSION_ERROR: PERMISSION_ERROR,
            RESOURCE_ERROR: RESOURCE_ERROR,
            HOST_ERROR: HOST_ERROR,
            "Clarifai account access is limited": "Check your Clarifai account plan and usage limits.",
            "Enter a valid Clarifai user ID and app ID": "Check your Clarifai user ID and app ID.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ClarifaiSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: ClarifaiSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, team_id, schema_name, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ClarifaiResumeConfig]:
        return ResumableSourceManager(inputs, ClarifaiResumeConfig)

    def source_for_pipeline(
        self,
        config: ClarifaiSourceConfig,
        resumable_source_manager: ResumableSourceManager[ClarifaiResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return ClarifaiClient(config, inputs.team_id, self.resolve_api_version(inputs.api_version)).source(
            inputs.schema_name, inputs.job_id, resumable_source_manager
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CLARIFAI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Clarifai",
            iconPath="/static/services/clarifai.png",
            docsUrl="https://docs.clarifai.com/control/authentication/pat/",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Create a personal access token in Clarifai under Settings > Secrets. "
                "Grant read access for models, workflows, datasets, and concepts that you want to sync. "
                "Allow their ListModels, ListWorkflows, ListDatasets, and ListConcepts endpoints. "
                "Enter the user ID and app ID of the app owner."
            ),
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="personal_access_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="user_id",
                        label="User ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="example-user",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="app_id",
                        label="App ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="example-app",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_host",
                        label="API host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://api.clarifai.com",
                        secret=False,
                    ),
                ],
            ),
        )
