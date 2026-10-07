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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.slash import SlashSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.slash.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.slash.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PERMISSION_ERROR,
    REQUEST_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.slash.slash import (
    SlashResumeConfig,
    slash_source,
    validate_credentials as validate_slash_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SlashSource(ResumableSource[SlashSourceConfig, SlashResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = "https://docs.slash.com/changelog"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SLASH

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": PERMISSION_ERROR,
            "400 Client Error": REQUEST_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SlashSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: SlashSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_slash_credentials(config, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SlashResumeConfig]:
        return ResumableSourceManager(inputs, SlashResumeConfig)

    def source_for_pipeline(
        self,
        config: SlashSourceConfig,
        resumable_source_manager: ResumableSourceManager[SlashResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return slash_source(
            config=config,
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
            name=ExternalDataSourceType.SLASH,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Slash",
            caption=(
                "Create an API key for your legal entity in the Slash dashboard. "
                "Use a read-only key. User-scoped keys also require the legal entity ID. "
                "Slash requires API access; contact support@joinslash.com if needed. "
                "Transaction date filters do not capture all later status changes. "
                "Use full refresh to reconcile older transactions."
            ),
            iconPath="/static/services/slash.png",
            keywords=["banking", "corporate cards", "transactions", "fintech"],
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
                        name="legal_entity_id",
                        label="Legal entity ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
