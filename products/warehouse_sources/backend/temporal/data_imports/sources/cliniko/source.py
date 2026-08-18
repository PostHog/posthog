from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.cliniko import (
    ClinikoResumeConfig,
    cliniko_source,
    validate_credentials as validate_cliniko_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cliniko import (
    ClinikoSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ClinikoSource(ResumableSource[ClinikoSourceConfig, ClinikoResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.api.cliniko.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLINIKO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Cliniko authentication failed. Please check your API key.",
            "403 Client Error": "Cliniko authentication failed. Please check your API key's permissions.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ClinikoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: ClinikoSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_cliniko_credentials(config.api_key):
            return True, None

        return False, "Invalid credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ClinikoResumeConfig]:
        return ResumableSourceManager[ClinikoResumeConfig](inputs, ClinikoResumeConfig)

    def source_for_pipeline(
        self,
        config: ClinikoSourceConfig,
        resumable_source_manager: ResumableSourceManager[ClinikoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return cliniko_source(
            api_key=config.api_key,
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
            name=SchemaExternalDataSourceType.CLINIKO,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            releaseStatus=ReleaseStatus.ALPHA,
            label="Cliniko",
            caption="Enter your Cliniko API key. You can generate one from your Cliniko account "
            "under **My Info > API Keys**. The clinic's region (shard) is detected automatically "
            "from the key.",
            docsUrl="https://posthog.com/docs/cdp/sources/cliniko",
            iconPath="/static/services/cliniko.png",
            keywords=["clinic", "practice management", "allied health"],
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
                ],
            ),
        )
