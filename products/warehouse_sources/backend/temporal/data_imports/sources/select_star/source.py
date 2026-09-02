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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.selectstar import (
    SelectStarSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.select_star.select_star import (
    SelectStarResumeConfig,
    select_star_source,
    validate_credentials as validate_selectstar_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.select_star.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SelectStarSource(ResumableSource[SelectStarSourceConfig, SelectStarResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.selectstar.com/select-star-api/overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SELECTSTAR

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Select Star rejected the API token. Generate a new token in "
            "Account Settings and reconnect.",
            "403 Client Error: Forbidden": "This Select Star token doesn't have permission to read the catalog. "
            "Check the user's role in Account Settings and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.select_star.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SelectStarSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: SelectStarSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_selectstar_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SelectStarResumeConfig]:
        return ResumableSourceManager[SelectStarResumeConfig](inputs, SelectStarResumeConfig)

    def source_for_pipeline(
        self,
        config: SelectStarSourceConfig,
        resumable_source_manager: ResumableSourceManager[SelectStarResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return select_star_source(
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

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SELECT_STAR,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Select Star",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Enter your Select Star API token to pull your data catalog into the PostHog Data warehouse.\n\n"
                "Create a token in Select Star under **Account Settings > Client API Token > Manage API Tokens "
                "> Create**. The token never expires and inherits the creating user's role. **Viewer** access "
                "is enough to read tables, columns, databases, schemas, tags, and BI dashboards."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/select-star",
            iconPath="/static/services/select_star.png",
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
