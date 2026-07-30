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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.recreation import (
    RecreationSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recreation.recreation import (
    RecreationResumeConfig,
    recreation_source,
    validate_credentials as validate_recreation_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recreation.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RecreationSource(ResumableSource[RecreationSourceConfig, RecreationResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://ridb.recreation.gov/docs"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RECREATION

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://ridb.recreation.gov": "Your RIDB API key is invalid or expired. Copy the key from your profile at ridb.recreation.gov and reconnect.",
            "403 Client Error: Forbidden for url: https://ridb.recreation.gov": "Your RIDB API key was rejected. Copy the key from your profile at ridb.recreation.gov and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.recreation.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: RecreationSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: RecreationSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_recreation_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RecreationResumeConfig]:
        return ResumableSourceManager[RecreationResumeConfig](inputs, RecreationResumeConfig)

    def source_for_pipeline(
        self,
        config: RecreationSourceConfig,
        resumable_source_manager: ResumableSourceManager[RecreationResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return recreation_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RECREATION,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Recreation.gov",
            caption="""Import public US federal recreation data from the Recreation Information Database (RIDB) behind Recreation.gov: recreation areas, facilities, campsites, tours, permit entrances, and more.

To get an API key, sign in at [ridb.recreation.gov](https://ridb.recreation.gov/), open your profile from the account menu, and copy the API key shown there.""",
            keywords=["ridb", "recreation.gov", "campgrounds", "campsites"],
            docsUrl="https://posthog.com/docs/cdp/sources/recreation",
            iconPath="/static/services/recreation.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Enter your RIDB API key",
                        secret=True,
                    ),
                ],
            ),
        )
