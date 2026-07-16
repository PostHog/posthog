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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import VapiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vapi.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    VAPI_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.vapi.vapi import (
    VapiResumeConfig,
    validate_credentials as validate_vapi_credentials,
    vapi_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class VapiSource(ResumableSource[VapiSourceConfig, VapiResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VAPI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.VAPI,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Vapi",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Vapi private API key to automatically pull your Vapi voice agent data into the PostHog Data warehouse.

You can find your private API key in the [Vapi dashboard](https://dashboard.vapi.ai) under **Organization settings** → **API keys**.
""",
            iconPath="/static/services/vapi.png",
            docsUrl="https://posthog.com/docs/cdp/sources/vapi",
            keywords=["voice", "ai agent", "calls", "telephony"],
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

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.vapi.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # An invalid or revoked Vapi API key surfaces as a requests HTTPError from
        # `raise_for_status()`. Match the stable status text and base host, not the
        # per-request path/query.
        return {
            "401 Client Error: Unauthorized for url: https://api.vapi.ai": "Your Vapi API key is invalid or has been revoked. Create a new private API key in the Vapi dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.vapi.ai": "Your Vapi API key does not have permission to read this data. Check the key's permissions in the Vapi dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: VapiSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = VAPI_ENDPOINTS[endpoint]
            has_incremental = len(endpoint_config.incremental_fields) > 0
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: VapiSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_vapi_credentials(config.api_key):
            return True, None

        return False, "Invalid Vapi API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[VapiResumeConfig]:
        return ResumableSourceManager[VapiResumeConfig](inputs, VapiResumeConfig)

    def source_for_pipeline(
        self,
        config: VapiSourceConfig,
        resumable_source_manager: ResumableSourceManager[VapiResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return vapi_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            db_incremental_field_earliest_value=inputs.db_incremental_field_earliest_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
