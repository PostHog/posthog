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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HatchetSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet import (
    HatchetResumeConfig,
    hatchet_source,
    resolve_connection,
    validate_credentials as validate_hatchet_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.settings import (
    ENDPOINTS,
    HATCHET_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HatchetSource(ResumableSource[HatchetSourceConfig, HatchetResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HATCHET

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HATCHET,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Hatchet",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter a Hatchet API token to sync your workflow runs, tasks, and events into the PostHog Data warehouse.

Create a tenant-scoped API token in your Hatchet dashboard under **Settings > API Tokens**. The token encodes your tenant and server URL, so that's usually all you need.

If you self-host Hatchet, or the token can't be decoded, set the **Host** and **Tenant id** fields to point the connection at your instance.""",
            iconPath="/static/services/hatchet.png",
            docsUrl="https://posthog.com/docs/cdp/sources/hatchet",
            keywords=["task queue", "workflows", "orchestration", "background jobs"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Bearer token from Settings > API Tokens",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="host",
                        label="Host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://cloud.onhatchet.run",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="tenant_id",
                        label="Tenant id",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Derived from the token when left blank",
                        secret=False,
                    ),
                ],
            ),
        )

    @property
    def connection_host_fields(self) -> list[str]:
        # The API token is sent to `host`; retargeting it must re-require the token so a preserved
        # secret can't be redirected at a server the editor controls.
        return ["host"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Hatchet API token is invalid or has expired. Create a new token in your Hatchet dashboard, then reconnect.",
            "403 Client Error": "Your Hatchet API token does not have access to this tenant. Check the token's tenant scope, then reconnect.",
            "Invalid Hatchet API token format": "The Hatchet API token could not be read. Paste the full token from your Hatchet dashboard.",
            "Could not decode the Hatchet API token": "The Hatchet API token could not be read. Paste the full token from your Hatchet dashboard.",
            "Could not determine the Hatchet tenant id": "The Hatchet tenant id could not be determined from the token. Enter it manually in the tenant id field.",
        }

    def get_schemas(
        self,
        config: HatchetSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = HATCHET_ENDPOINTS[endpoint]
            supports_incremental = endpoint_config.supports_time_window and bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=supports_incremental,
                supports_append=supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                detected_primary_keys=endpoint_config.primary_keys,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: HatchetSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_hatchet_credentials(config.api_token, config.host or None, config.tenant_id or None, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HatchetResumeConfig]:
        return ResumableSourceManager[HatchetResumeConfig](inputs, HatchetResumeConfig)

    def source_for_pipeline(
        self,
        config: HatchetSourceConfig,
        resumable_source_manager: ResumableSourceManager[HatchetResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        connection = resolve_connection(config.api_token, config.host or None, config.tenant_id or None)
        return hatchet_source(
            api_token=config.api_token,
            connection=connection,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
