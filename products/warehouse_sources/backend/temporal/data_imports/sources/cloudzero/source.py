from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudzero.cloudzero import (
    CloudzeroResumeConfig,
    cloudzero_source,
    validate_credentials as validate_cloudzero_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudzero.settings import (
    COST_TYPE_OPTIONS,
    ENDPOINTS,
    GRANULARITY_OPTIONS,
    INCREMENTAL_FIELDS,
    PARTITION_KEYS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudzero import (
    CloudzeroSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _parse_group_by(group_by: str | None) -> list[str]:
    if not group_by:
        return []
    return [dimension.strip() for dimension in group_by.split(",") if dimension.strip()]


@SourceRegistry.register
class CloudzeroSource(ResumableSource[CloudzeroSourceConfig, CloudzeroResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://docs.cloudzero.com/reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLOUDZERO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "403 Client Error: Forbidden": "CloudZero authentication failed. Please check your API key and its assigned scopes.",
            "Unauthorized": "CloudZero authentication failed. Please check your API key and its assigned scopes.",
            "410 Client Error: Gone": (
                "CloudZero's paged result cache expired (results are only valid for 24 hours). "
                "Please retry the sync to start a fresh query."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.cloudzero.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CloudzeroSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: CloudzeroSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_cloudzero_credentials(config.api_key):
            return True, None

        return False, "Invalid credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CloudzeroResumeConfig]:
        return ResumableSourceManager[CloudzeroResumeConfig](inputs, CloudzeroResumeConfig)

    def source_for_pipeline(
        self,
        config: CloudzeroSourceConfig,
        resumable_source_manager: ResumableSourceManager[CloudzeroResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        group_by = _parse_group_by(config.group_by)
        resource = cloudzero_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            granularity=config.granularity,
            cost_type=config.cost_type,
            group_by=group_by,
        )

        primary_keys = ["usage_date", *group_by] if inputs.schema_name == "Costs" else ["id"]
        partition_key = PARTITION_KEYS.get(inputs.schema_name)

        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=primary_keys,
            column_hints=resource.column_hints,
            partition_count=1 if partition_key else None,
            partition_size=1 if partition_key else None,
            partition_mode="datetime" if partition_key else None,
            partition_format="month" if partition_key else None,
            partition_keys=[partition_key] if partition_key else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLOUDZERO,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="CloudZero",
            caption=(
                "Enter your CloudZero API key. The key must be granted the `billing:read_costs` and "
                "`billing:read_dimensions` scopes in CloudZero under Settings > API Keys."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/cloudzero",
            iconPath="/static/services/cloudzero.png",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["cloud cost", "finops", "billing"],
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
                    SourceFieldSelectConfig(
                        name="granularity",
                        label="Granularity",
                        required=True,
                        defaultValue="daily",
                        options=[
                            SourceFieldSelectConfigOption(label=option.capitalize(), value=option)
                            for option in GRANULARITY_OPTIONS
                        ],
                    ),
                    SourceFieldSelectConfig(
                        name="cost_type",
                        label="Cost type",
                        required=True,
                        defaultValue="real_cost",
                        options=[
                            SourceFieldSelectConfigOption(label=option.replace("_", " ").capitalize(), value=option)
                            for option in COST_TYPE_OPTIONS
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="group_by",
                        label="Group costs by dimensions (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="e.g. service,account",
                        secret=False,
                    ),
                ],
            ),
        )
