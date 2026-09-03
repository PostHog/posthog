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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.metronome import (
    MetronomeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metronome.metronome import (
    MetronomeResumeConfig,
    metronome_source,
    validate_credentials as validate_metronome_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metronome.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MetronomeSource(ResumableSource[MetronomeSourceConfig, MetronomeResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Metronome exposes no pinnable API version. `/v1/` and `/v2/` are route namespaces that
    # coexist permanently — v2 contracts sit alongside v1 rate cards and packages — and no header,
    # path or query parameter selects a version.
    api_docs_url = "https://docs.metronome.com/api-reference/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.METRONOME

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Metronome rejected the API token. Create a new one under Developer > API tokens and reconnect.",
            "403 Client Error: Forbidden for url": "The Metronome API token can't read this data. Check the token's scopes, or create an unscoped one under Developer > API tokens.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.metronome.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MetronomeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: MetronomeSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_metronome_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MetronomeResumeConfig]:
        return ResumableSourceManager[MetronomeResumeConfig](inputs, MetronomeResumeConfig)

    def source_for_pipeline(
        self,
        config: MetronomeSourceConfig,
        resumable_source_manager: ResumableSourceManager[MetronomeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return metronome_source(
            api_key=config.api_key,
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
            name=SchemaExternalDataSourceType.METRONOME,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            keywords=["billing", "usage-based billing"],
            label="Metronome",
            caption="Create an API token in Metronome under **Developer > API tokens**. Metronome shows the token once, so copy it before closing the dialog.",
            docsUrl="https://posthog.com/docs/cdp/sources/metronome",
            iconPath="/static/services/metronome.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
