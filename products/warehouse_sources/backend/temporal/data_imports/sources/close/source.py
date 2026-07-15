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
from products.warehouse_sources.backend.temporal.data_imports.sources.close.close import (
    CloseResumeConfig,
    close_source,
    validate_credentials as validate_close_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.close.settings import CLOSE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CloseSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CloseSource(ResumableSource[CloseSourceConfig, CloseResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://developer.close.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLOSE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Close authentication failed. Please check your API key.",
            "403 Client Error: Forbidden for url": "Your Close API key does not have access to this resource. Please check the key's permissions.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.close.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CloseSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint_config.name,
                supports_incremental=len(endpoint_config.incremental_fields) > 0,
                supports_append=len(endpoint_config.incremental_fields) > 0,
                incremental_fields=endpoint_config.incremental_fields,
            )
            for endpoint_config in CLOSE_ENDPOINTS.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: CloseSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not config.api_key:
            return False, "Close API key is required"

        if validate_close_credentials(config.api_key):
            return True, None

        return False, "Invalid Close API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CloseResumeConfig]:
        return ResumableSourceManager[CloseResumeConfig](inputs, CloseResumeConfig)

    def source_for_pipeline(
        self,
        config: CloseSourceConfig,
        resumable_source_manager: ResumableSourceManager[CloseResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return close_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLOSE,
            category=DataWarehouseSourceCategory.CRM,
            label="Close",
            caption=(
                "Import your CRM data from Close. Create an API key under "
                "**Settings → Developer → API Keys** in Close and paste it below. "
                "The key needs read access to the resources you want to sync."
            ),
            iconPath="/static/services/close.png",
            docsUrl="https://posthog.com/docs/cdp/sources/close",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="api_...",
                        secret=True,
                    ),
                ],
            ),
        )
