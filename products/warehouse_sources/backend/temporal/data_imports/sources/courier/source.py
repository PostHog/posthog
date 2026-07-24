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
from products.warehouse_sources.backend.temporal.data_imports.sources.courier.courier import (
    CourierResumeConfig,
    courier_source,
    validate_credentials as validate_courier_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.courier.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.courier import (
    CourierSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CourierSource(ResumableSource[CourierSourceConfig, CourierResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://www.courier.com/docs/reference/get-started/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COURIER

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "403 Client Error: Forbidden for url": "Your Courier API key is invalid or has been revoked. Please generate a new key in the Courier dashboard and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.courier.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CourierSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: CourierSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_courier_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CourierResumeConfig]:
        return ResumableSourceManager[CourierResumeConfig](inputs, CourierResumeConfig)

    def source_for_pipeline(
        self,
        config: CourierSourceConfig,
        resumable_source_manager: ResumableSourceManager[CourierResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return courier_source(
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
            name=SchemaExternalDataSourceType.COURIER,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Courier",
            caption="Use an API key from the Courier dashboard under **Settings → API Keys**. Either the Live or Test key works; the key determines which environment's data is synced.",
            docsUrl="https://posthog.com/docs/cdp/sources/courier",
            iconPath="/static/services/courier.png",
            keywords=["notifications", "messaging"],
            releaseStatus=ReleaseStatus.ALPHA,
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
