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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.telnyx import TelnyxSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.telnyx.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    TELNYX_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.telnyx.telnyx import (
    TelnyxResumeConfig,
    telnyx_source,
    validate_credentials as validate_telnyx_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TelnyxSource(ResumableSource[TelnyxSourceConfig, TelnyxResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developers.telnyx.com/docs/api/v2/detail-records/detail-record-search"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TELNYX

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Your Telnyx API key is invalid or has expired. Generate a new key from the Telnyx portal and reconnect.",
            "403 Client Error: Forbidden": "Your Telnyx API key doesn't have permission for this request. Check the key's scopes in the Telnyx portal and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.telnyx.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TelnyxSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: TelnyxSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_telnyx_credentials(config.api_key):
            return True, None

        return False, "Invalid Telnyx API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TelnyxResumeConfig]:
        return ResumableSourceManager[TelnyxResumeConfig](inputs, TelnyxResumeConfig)

    def source_for_pipeline(
        self,
        config: TelnyxSourceConfig,
        resumable_source_manager: ResumableSourceManager[TelnyxResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        endpoint = TELNYX_ENDPOINTS[inputs.schema_name]
        resource = telnyx_source(
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
        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=endpoint.primary_key,
            column_hints=resource.column_hints,
            partition_mode="datetime",
            partition_format="month",
            partition_keys=[endpoint.partition_key],
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TELNYX,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Telnyx",
            keywords=["cpaas", "sms", "voice"],
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Enter your Telnyx API v2 key to pull messaging, voice, verify, wireless, and media "
                "storage detail records into the PostHog Data warehouse. Generate a key from "
                "**API Keys** in the Telnyx portal."
            ),
            iconPath="/static/services/telnyx.png",
            docsUrl="https://posthog.com/docs/cdp/sources/telnyx",
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
