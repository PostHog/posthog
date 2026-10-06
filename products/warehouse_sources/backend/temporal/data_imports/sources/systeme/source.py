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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.systeme import (
    SystemeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.systeme.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.systeme.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    NON_RETRYABLE_ERRORS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.systeme.systeme import (
    SystemeResumeConfig,
    systeme_source,
    validate_credentials as validate_systeme_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SystemeSource(ResumableSource[SystemeSourceConfig, SystemeResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = "https://developer.systeme.io/reference/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SYSTEME

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return dict(NON_RETRYABLE_ERRORS)

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SystemeSourceConfig,
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
            descriptions={
                "contacts": "Incremental sync imports new registrations. Use full refresh to capture changes to older contacts."
            },
        )

    def validate_credentials(
        self,
        config: SystemeSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_systeme_credentials(config.api_key, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SystemeResumeConfig]:
        return ResumableSourceManager(inputs, SystemeResumeConfig)

    def source_for_pipeline(
        self,
        config: SystemeSourceConfig,
        resumable_source_manager: ResumableSourceManager[SystemeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return systeme_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SYSTEME,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Systeme.io",
            iconPath="/static/services/systeme.png",
            caption="Create an API key in your Systeme.io profile settings under Public API keys.",
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
                    )
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
