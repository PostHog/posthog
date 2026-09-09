from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gleif import GleifSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gleif.gleif import (
    GleifResumeConfig,
    gleif_source,
    validate_credentials as validate_gleif_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gleif.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GleifSource(ResumableSource[GleifSourceConfig, GleifResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://www.gleif.org/en/lei-data/gleif-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GLEIF

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.gleif.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: GleifSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: GleifSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_gleif_credentials():
            return True, None
        return False, "Could not reach the GLEIF API. Please try again in a moment."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GleifResumeConfig]:
        return ResumableSourceManager[GleifResumeConfig](inputs, GleifResumeConfig)

    def source_for_pipeline(
        self,
        config: GleifSourceConfig,
        resumable_source_manager: ResumableSourceManager[GleifResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return gleif_source(
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GLEIF,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            keywords=["lei", "legal entity identifier"],
            label="GLEIF (Global Legal Entity Identifier Foundation)",
            caption=(
                "Import Legal Entity Identifier (LEI) reference data from GLEIF's free, public "
                "registry. No API key or account is required."
            ),
            iconPath="/static/services/gleif.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(list[FieldType], []),
        )
