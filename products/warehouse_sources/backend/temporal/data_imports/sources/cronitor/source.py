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
from products.warehouse_sources.backend.temporal.data_imports.sources.cronitor.cronitor import (
    CronitorResumeConfig,
    cronitor_source,
    validate_credentials as validate_cronitor_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cronitor.settings import (
    CRONITOR_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CronitorSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CronitorSource(ResumableSource[CronitorSourceConfig, CronitorResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CRONITOR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CRONITOR,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Cronitor",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Import your Cronitor monitors, their recent job invocations, and time-series reliability metrics into the PostHog Data warehouse.

Create an API key with the `monitor:read` scope under **Settings → API keys** in your Cronitor account, and enter it here.""",
            iconPath="/static/services/cronitor.png",
            docsUrl="https://posthog.com/docs/cdp/sources/cronitor",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.cronitor.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch` calls `raise_for_status()`.
            # Retrying can never fix a credential/scope problem, so fail the sync. Match the stable
            # status text, not the per-request path.
            "401 Client Error: Unauthorized": "Your Cronitor API key is invalid or has been revoked. Create a new key in your Cronitor account's API settings, then reconnect.",
            "403 Client Error: Forbidden": "Your Cronitor API key is missing the monitor:read scope needed to sync this data. Update the key's scopes, then reconnect.",
        }

    def get_schemas(
        self,
        config: CronitorSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            supports_incremental = len(CRONITOR_ENDPOINTS[endpoint].incremental_fields) > 0
            return SourceSchema(
                name=endpoint,
                supports_incremental=supports_incremental,
                supports_append=supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: CronitorSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        ok, status_code = validate_cronitor_credentials(config.api_key)
        if ok:
            return True, None
        if status_code in (401, 403):
            return False, "Invalid Cronitor API key. Make sure the key has the monitor:read scope."
        return False, "Could not connect to Cronitor with the provided API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CronitorResumeConfig]:
        return ResumableSourceManager[CronitorResumeConfig](inputs, CronitorResumeConfig)

    def source_for_pipeline(
        self,
        config: CronitorSourceConfig,
        resumable_source_manager: ResumableSourceManager[CronitorResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return cronitor_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
