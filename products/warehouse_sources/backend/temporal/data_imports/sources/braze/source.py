from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze import (
    BRAZE_FORBIDDEN_MSG,
    BrazeResumeConfig,
    braze_source,
    validate_credentials as validate_braze_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.braze.settings import (
    BRAZE_DATA_SERIES_ENDPOINTS,
    BRAZE_PROBE_TARGETS,
    DATA_SERIES_LOOKBACK_SECONDS,
    DEFAULT_PROBE_TARGET,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.braze import BrazeSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BrazeSource(ResumableSource[BrazeSourceConfig, BrazeResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://www.braze.com/docs/api/basics/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BRAZE

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.braze.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BRAZE,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Braze",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Braze REST API key and endpoint to sync your Braze data into the PostHog Data warehouse.

You can create a REST API key in your Braze dashboard under **Settings → API Keys**. Grant the following endpoint permissions for the data you want to sync:
- `campaigns.list`
- `campaigns.data_series`
- `campaigns.details`
- `canvas.list`
- `canvas.data_series`
- `canvas.details`
- `segments.list`
- `segments.data_series`
- `events.list`
- `events.data_series`
- `kpi.dau.data_series`
- `kpi.mau.data_series`
- `kpi.new_users.data_series`
- `kpi.uninstalls.data_series`
- `templates.email.list`
- `content_blocks.list`

Your REST endpoint must match your Braze dashboard's region — see [Braze's API overview](https://www.braze.com/docs/api/basics/#endpoints) for the list of endpoints.""",
            iconPath="/static/services/braze.png",
            docsUrl="https://posthog.com/docs/cdp/sources/braze",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="REST API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="00000000-0000-0000-0000-000000000000",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="url",
                        label="REST endpoint URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://rest.iad-01.braze.com",
                        secret=False,
                    ),
                ],
            ),
        )

    @property
    def connection_host_fields(self) -> list[str]:
        # The REST API key is sent to whatever host `url` points at, so retargeting
        # it must re-require the key (prevents credential exfiltration to another host).
        return ["url"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Braze API key. Please generate a new REST API key and reconnect.",
            "403 Client Error": "Your Braze API key lacks permission for this endpoint. Grant the required endpoint permission and try again.",
        }

    def get_schemas(
        self,
        config: BrazeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(
            ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=tuple(BRAZE_DATA_SERIES_ENDPOINTS)
        )
        for schema in schemas:
            if schema.name in BRAZE_DATA_SERIES_ENDPOINTS:
                schema.default_incremental_lookback_seconds = DATA_SERIES_LOOKBACK_SECONDS
        return schemas

    def validate_credentials(
        self, config: BrazeSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in BRAZE_PROBE_TARGETS:
            return False, f"Unknown Braze schema: {schema_name!r}"
        probe_target = BRAZE_PROBE_TARGETS[schema_name] if schema_name is not None else DEFAULT_PROBE_TARGET
        valid, error = validate_braze_credentials(config.api_key, config.url, probe_target, team_id)

        # A scoped key may legitimately lack the probe endpoint's permission at
        # source-create time; only enforce per-endpoint scope when validating a
        # specific schema.
        if not valid and schema_name is None and error == BRAZE_FORBIDDEN_MSG:
            return True, None

        return valid, error

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BrazeResumeConfig]:
        return ResumableSourceManager[BrazeResumeConfig](inputs, BrazeResumeConfig)

    def source_for_pipeline(
        self,
        config: BrazeSourceConfig,
        resumable_source_manager: ResumableSourceManager[BrazeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return braze_source(
            api_key=config.api_key,
            base_url=config.url,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
