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
from products.warehouse_sources.backend.temporal.data_imports.sources.descope.descope import (
    DescopeResumeConfig,
    descope_source,
    validate_credentials as validate_descope_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.descope.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.descope import (
    DescopeSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DescopeSource(ResumableSource[DescopeSourceConfig, DescopeResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.descope.com/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DESCOPE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.descope.com": "Descope authentication failed. Please check your Project ID and Management Key.",
            "403 Client Error: Forbidden for url: https://api.descope.com": "Descope authentication failed. Please check your Project ID and Management Key.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.descope.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DescopeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: DescopeSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_descope_credentials(config.project_id, config.management_key):
            return True, None

        return False, "Invalid credentials. Please check your Project ID and Management Key."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DescopeResumeConfig]:
        return ResumableSourceManager[DescopeResumeConfig](inputs, DescopeResumeConfig)

    def source_for_pipeline(
        self,
        config: DescopeSourceConfig,
        resumable_source_manager: ResumableSourceManager[DescopeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return descope_source(
            project_id=config.project_id,
            management_key=config.management_key,
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
            name=SchemaExternalDataSourceType.DESCOPE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Descope",
            caption="Sync users, audit trail events, tenants, roles, and access keys from your Descope project. Requires a Management Key, generated from the [Descope Console](https://app.descope.com) under Project Settings > Company/Management Keys.",
            docsUrl="https://posthog.com/docs/cdp/sources/descope",
            releaseStatus=ReleaseStatus.ALPHA,
            iconPath="/static/services/descope.png",
            keywords=["ciam"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="project_id",
                        label="Project ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="P2...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="management_key",
                        label="Management key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
