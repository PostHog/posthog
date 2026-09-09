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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.workiz import WorkizSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.workiz.settings import (
    DATE_WINDOWED_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PARTITION_KEYS,
    PRIMARY_KEYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.workiz.workiz import (
    WorkizResumeConfig,
    validate_credentials as validate_workiz_credentials,
    workiz_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WorkizSource(ResumableSource[WorkizSourceConfig, WorkizResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog -- safe for public docs
    api_docs_url = "https://developer.workiz.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WORKIZ

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Workiz authentication failed. Please check your API token.",
            "403 Client Error": "Workiz authentication failed. Please check your API token.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.workiz.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: WorkizSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: WorkizSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_workiz_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WorkizResumeConfig]:
        return ResumableSourceManager[WorkizResumeConfig](inputs, WorkizResumeConfig)

    def source_for_pipeline(
        self,
        config: WorkizSourceConfig,
        resumable_source_manager: ResumableSourceManager[WorkizResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        resource = workiz_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
        partition_key = PARTITION_KEYS.get(inputs.schema_name)
        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=PRIMARY_KEYS.get(inputs.schema_name, ["id"]),
            column_hints=resource.column_hints,
            partition_count=1 if partition_key else None,
            partition_size=1 if partition_key else None,
            partition_mode="datetime" if partition_key else None,
            partition_format="month" if partition_key else None,
            partition_keys=[partition_key] if partition_key else None,
            # Jobs/Leads are sorted newest-first with no way to request ascending order; Team/
            # TimeOff return their full list in one shot so sort order there is moot.
            sort_mode="desc" if inputs.schema_name in DATE_WINDOWED_ENDPOINTS else "asc",
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WORKIZ,
            category=DataWarehouseSourceCategory.CRM,
            label="Workiz",
            caption=(
                "Sync jobs, leads, team members, and time off from Workiz. Requires the "
                "Developer API add-on, enabled from Settings > Integrations > Developer in Workiz."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/workiz",
            iconPath="/static/services/workiz.png",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["field service", "jobs", "leads"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
