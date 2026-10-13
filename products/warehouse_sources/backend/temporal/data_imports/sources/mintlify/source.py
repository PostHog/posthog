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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mintlify import (
    MintlifySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mintlify.mintlify import (
    MintlifyResumeConfig,
    mintlify_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mintlify.settings import (
    API_VERSION,
    ENDPOINTS,
    HTTP_ERRORS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MintlifySource(ResumableSource[MintlifySourceConfig, MintlifyResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://www.mintlify.com/docs/api/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MINTLIFY

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {f"{status} Client Error": message for status, message in HTTP_ERRORS.items()}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mintlify.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MintlifySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=INCREMENTAL_FIELDS)

    def validate_credentials(
        self,
        config: MintlifySourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MintlifyResumeConfig]:
        return ResumableSourceManager(inputs, MintlifyResumeConfig)

    def source_for_pipeline(
        self,
        config: MintlifySourceConfig,
        resumable_source_manager: ResumableSourceManager[MintlifyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return mintlify_source(
            config=config,
            endpoint_name=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MINTLIFY,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Mintlify",
            iconPath="/static/services/mintlify.png",
            keywords=["docs", "documentation", "analytics", "assistant"],
            caption=(
                "Create an admin API key and copy your project ID from "
                "[Mintlify's API keys page](https://app.mintlify.com/settings/organization/api-keys). "
                "A Pro or Enterprise plan is required. Analytics endpoints share a limit of 100 requests per organization per hour."
            ),
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Admin API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="mint_...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="project_id",
                        label="Project ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
