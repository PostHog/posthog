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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.debugbear.debugbear import (
    debugbear_source,
    validate_credentials as validate_debugbear_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.debugbear.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.debugbear import (
    DebugbearSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DebugbearSource(SimpleSource[DebugbearSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://www.debugbear.com/docs/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DEBUGBEAR

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your DebugBear API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error": "Your DebugBear API key doesn't have permission for this request. Use an Admin API key (Account settings > API Keys) and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.debugbear.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DebugbearSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: DebugbearSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_debugbear_credentials(config.api_key)

    def source_for_pipeline(self, config: DebugbearSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return debugbear_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DEBUGBEAR,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="DebugBear",
            caption="Sync DebugBear's monitored projects and synthetic Lighthouse / Core Web Vitals test results into your warehouse.",
            docsUrl="https://posthog.com/docs/cdp/sources/debugbear",
            iconPath="/static/services/debugbear.png",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["core web vitals", "lighthouse", "web performance"],
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
                        caption="Use an Admin API key so PostHog can list every monitored project. Generate one from DebugBear's account settings — see the [API docs](https://www.debugbear.com/docs/api).",
                    ),
                ],
            ),
        )
