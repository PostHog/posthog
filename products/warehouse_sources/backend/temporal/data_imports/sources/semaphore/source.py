from typing import cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.semaphore import (
    SemaphoreSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semaphore.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semaphore.semaphore import (
    SemaphoreResumeConfig,
    semaphore_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semaphore.settings import (
    API_DOCS_URL,
    AUTH_ERROR,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    NOT_FOUND_ERROR,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SemaphoreSource(ResumableSource[SemaphoreSourceConfig, SemaphoreResumeConfig]):
    lists_tables_without_credentials = True
    # Semaphore Cloud documents v1alpha as its public API despite the version name.
    supported_versions = ("v1alpha",)
    default_version = "v1alpha"
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SEMAPHORE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": PERMISSION_ERROR,
            "404 Client Error": NOT_FOUND_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SemaphoreSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only={"workflows"})

    def validate_credentials(
        self,
        config: SemaphoreSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            return validate_credentials(config, self.resolve_api_version(api_version))
        except ValueError as error:
            return False, str(error)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SemaphoreResumeConfig]:
        return ResumableSourceManager(inputs, SemaphoreResumeConfig)

    def source_for_pipeline(
        self,
        config: SemaphoreSourceConfig,
        resumable_source_manager: ResumableSourceManager[SemaphoreResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return semaphore_source(config, inputs, resumable_source_manager, self.resolve_api_version(inputs.api_version))

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SEMAPHORE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Semaphore (Semaphore CI)",
            iconPath="/static/services/semaphore.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="Copy your API token from [Semaphore account settings](https://me.semaphoreci.com/account). "
            "Enter your organization subdomain and the project ID to import.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="",
                    ),
                    SourceFieldInputConfig(
                        name="organization",
                        label="Organization subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        secret=False,
                        placeholder="example",
                    ),
                    SourceFieldInputConfig(
                        name="project_id",
                        label="Project ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        secret=False,
                        placeholder="00000000-0000-4000-8000-000000000001",
                    ),
                ],
            ),
        )
