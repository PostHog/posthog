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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wasabi import WasabiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.settings import (
    BUCKET_UTILIZATIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    UTILIZATION_LOOKBACK_SECONDS,
    UTILIZATIONS,
    WASABI_BASE_URL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.wasabi import (
    WasabiResumeConfig,
    validate_credentials as validate_wasabi_credentials,
    wasabi_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WasabiSource(ResumableSource[WasabiSourceConfig, WasabiResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.wasabi.com/apidocs/account-control-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WASABI

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            f"401 Client Error: Unauthorized for url: {WASABI_BASE_URL}": "Your Wasabi API key is invalid or expired. Please generate a new key and reconnect.",
            f"403 Client Error: Forbidden for url: {WASABI_BASE_URL}": "Wasabi rejected the API key. Check that Wasabi Account Control API access is enabled on your Control Account and the key is valid.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: WasabiSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # The date-window walk re-reads a boundary day each run, so append syncs would
        # duplicate rows — utilization endpoints are merge-only.
        schemas = build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            merge_only=(UTILIZATIONS, BUCKET_UTILIZATIONS),
        )
        for schema in schemas:
            if schema.name in (UTILIZATIONS, BUCKET_UTILIZATIONS):
                schema.default_incremental_lookback_seconds = UTILIZATION_LOOKBACK_SECONDS
        return schemas

    def validate_credentials(
        self,
        config: WasabiSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_wasabi_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WasabiResumeConfig]:
        return ResumableSourceManager[WasabiResumeConfig](inputs, WasabiResumeConfig)

    def source_for_pipeline(
        self,
        config: WasabiSourceConfig,
        resumable_source_manager: ResumableSourceManager[WasabiResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return wasabi_source(
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
            name=SchemaExternalDataSourceType.WASABI,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            label="Wasabi",
            caption="""Import sub-account, usage, and invoice data from the Wasabi Account Control API (WACA) into the PostHog Data warehouse.

WACA is available to Wasabi Control Accounts (partners managing sub-accounts). To get an API key, enable Wasabi Account Control API access on your Control Account — see [Wasabi's documentation](https://docs.wasabi.com/apidocs/account-control-api) for details.
""",
            releaseStatus=ReleaseStatus.ALPHA,
            docsUrl="https://posthog.com/docs/cdp/sources/wasabi",
            iconPath="/static/services/wasabi.png",
            keywords=["waca", "wasabi account control"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Enter your Wasabi Account Control API key",
                        secret=True,
                    ),
                ],
            ),
        )
