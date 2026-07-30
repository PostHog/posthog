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
from products.warehouse_sources.backend.temporal.data_imports.sources.dovetail.dovetail import (
    DovetailResumeConfig,
    dovetail_source,
    validate_credentials as validate_dovetail_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dovetail.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dovetail import (
    DovetailSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DovetailSource(ResumableSource[DovetailSourceConfig, DovetailResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Dovetail's API has no versioned path/header (a bare `/v1/` that's never changed and isn't a
    # documented version choice) - only the docs URL is worth pinning.
    api_docs_url = "https://developers.dovetail.com/docs/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DOVETAIL

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Dovetail rejected the API token. Please generate a new personal API key from workspace settings and reconnect.",
            "403 Client Error: Forbidden for url": "Your Dovetail API token does not have permission for this resource.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.dovetail.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DovetailSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: DovetailSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_dovetail_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DovetailResumeConfig]:
        return ResumableSourceManager[DovetailResumeConfig](inputs, DovetailResumeConfig)

    def source_for_pipeline(
        self,
        config: DovetailSourceConfig,
        resumable_source_manager: ResumableSourceManager[DovetailResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return dovetail_source(
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
            name=SchemaExternalDataSourceType.DOVETAIL,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Dovetail",
            docsUrl="https://posthog.com/docs/cdp/sources/dovetail",
            iconPath="/static/services/dovetail.png",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["user research", "customer research", "qualitative research"],
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
                        caption="Generate a personal API key from **Settings > Account > Personal API keys** in Dovetail.",
                    ),
                ],
            ),
        )
