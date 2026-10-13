from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.braintrust.braintrust import (
    BraintrustResumeConfig,
    braintrust_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.braintrust.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.braintrust.settings import AUTH_ERRORS, ENDPOINTS
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.braintrust import (
    BraintrustSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BraintrustSource(ResumableSource[BraintrustSourceConfig, BraintrustResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://www.braintrust.dev/docs/reference/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BRAINTRUST

    @property
    def connection_host_fields(self) -> list[str]:
        return ["api_url"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {f"{status} Client Error": message for status, message in AUTH_ERRORS.items()}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: BraintrustSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: BraintrustSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BraintrustResumeConfig]:
        return ResumableSourceManager(inputs, BraintrustResumeConfig)

    def source_for_pipeline(
        self,
        config: BraintrustSourceConfig,
        resumable_source_manager: ResumableSourceManager[BraintrustResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return braintrust_source(config, inputs.schema_name, inputs.team_id, inputs.job_id, resumable_source_manager)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BRAINTRUST,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            keywords=["llm", "evals", "ai"],
            label="Braintrust",
            iconPath="/static/services/braintrust.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="Create an API key in Braintrust organization settings. Give it read access to the selected resources.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="api_url",
                        label="API URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://api.braintrust.dev",
                        secret=False,
                        caption="Enter your API URL from Braintrust Settings > Data plane. Use your regional or self-hosted URL when applicable.",
                    ),
                ],
            ),
        )
