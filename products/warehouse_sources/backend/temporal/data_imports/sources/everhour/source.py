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
from products.warehouse_sources.backend.temporal.data_imports.sources.everhour.everhour import (
    EverhourResumeConfig,
    everhour_source,
    validate_credentials as validate_everhour_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.everhour.settings import (
    ENDPOINTS,
    EVERHOUR_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import EverhourSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class EverhourSource(ResumableSource[EverhourSourceConfig, EverhourResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EVERHOUR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.EVERHOUR,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Everhour",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Everhour API key to pull your Everhour time-tracking data into the PostHog Data warehouse.

You can find your API key in your [Everhour profile settings](https://app.everhour.com/#/account/profile) under the API section.

Using the API requires a paid Everhour plan.""",
            iconPath="/static/services/everhour.png",
            docsUrl="https://posthog.com/docs/cdp/sources/everhour",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.everhour.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
            # Retrying can never satisfy a credential problem, so stop the sync. Match the stable
            # status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.everhour.com": "Your Everhour API key is invalid or has been revoked. Generate a new key in your Everhour profile settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.everhour.com": "Your Everhour API key does not have permission to access this data. Check the key's permissions in Everhour, then reconnect.",
        }

    def get_schemas(
        self,
        config: EverhourSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = EVERHOUR_ENDPOINTS[endpoint]
            has_incremental = INCREMENTAL_FIELDS.get(endpoint) is not None
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
        self, config: EverhourSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_everhour_credentials(config.api_key):
            return True, None

        return False, "Invalid Everhour API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[EverhourResumeConfig]:
        return ResumableSourceManager[EverhourResumeConfig](inputs, EverhourResumeConfig)

    def source_for_pipeline(
        self,
        config: EverhourSourceConfig,
        resumable_source_manager: ResumableSourceManager[EverhourResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return everhour_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
