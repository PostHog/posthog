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
from products.warehouse_sources.backend.temporal.data_imports.sources.donorbox.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.donorbox.donorbox import (
    DonorboxResumeConfig,
    donorbox_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.donorbox.settings import (
    API_DOCS_URL,
    API_VERSION,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    NON_RETRYABLE_ERRORS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.donorbox import (
    DonorboxSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DonorboxSource(ResumableSource[DonorboxSourceConfig, DonorboxResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DONORBOX

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return dict(NON_RETRYABLE_ERRORS)

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DonorboxSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=INCREMENTAL_FIELDS)

    def validate_credentials(
        self,
        config: DonorboxSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, schema_name, api_version or API_VERSION)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DonorboxResumeConfig]:
        return ResumableSourceManager(inputs, DonorboxResumeConfig)

    def source_for_pipeline(
        self,
        config: DonorboxSourceConfig,
        resumable_source_manager: ResumableSourceManager[DonorboxResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return donorbox_source(
            config=config,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            api_version=inputs.api_version or API_VERSION,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DONORBOX,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Donorbox",
            iconPath="/static/services/donorbox.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "In Donorbox, open Account > API & Zapier Integration. Enable API access, then select Set new API Key. "
                "API access requires a paid subscription. Use your organization login email. "
                "Incremental sync uses donation dates and plan start dates. "
                "Use full refresh to capture changes to older records."
            ),
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="email",
                        label="Organization login email",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=True,
                        placeholder="you@example.com",
                        secret=False,
                    ),
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
