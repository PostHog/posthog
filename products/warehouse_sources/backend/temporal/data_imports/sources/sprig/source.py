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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sprig import SprigSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sprig.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sprig.sprig import (
    SprigResumeConfig,
    sprig_source,
    validate_credentials as validate_sprig_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SprigSource(ResumableSource[SprigSourceConfig, SprigResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.sprig.com/reference/sprig-api/overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SPRIG

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SPRIG,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Sprig",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Sprig API key to automatically pull your survey and response data into the PostHog Data warehouse.

Find your API key under **Integrations > Enrichment > Data Import API** in Sprig (Admin or Developer role required). Free/Starter plans need to contact [support@sprig.com](mailto:support@sprig.com) to enable API access first.""",
            iconPath="/static/services/sprig.png",
            docsUrl="https://posthog.com/docs/cdp/sources/sprig",
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

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.sprig.com": "Your Sprig API key is invalid or has been revoked. Create a new API key in Sprig under Integrations > Enrichment > Data Import API, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.sprig.com": "Your Sprig API key does not have permission to read this data. Check the key's environment/permissions in Sprig, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.sprig.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SprigSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: SprigSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_sprig_credentials(config.api_key):
            return True, None

        return False, "Invalid Sprig API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SprigResumeConfig]:
        return ResumableSourceManager[SprigResumeConfig](inputs, SprigResumeConfig)

    def source_for_pipeline(
        self,
        config: SprigSourceConfig,
        resumable_source_manager: ResumableSourceManager[SprigResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return sprig_source(
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
