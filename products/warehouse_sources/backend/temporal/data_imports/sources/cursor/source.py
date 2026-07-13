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
from products.warehouse_sources.backend.temporal.data_imports.sources.cursor.cursor import (
    CURSOR_BASE_URL,
    CursorResumeConfig,
    cursor_source,
    validate_credentials as validate_cursor_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cursor.settings import (
    CURSOR_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CursorSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CursorSource(ResumableSource[CursorSourceConfig, CursorResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CURSOR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CURSOR,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Cursor",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Cursor Admin API key to automatically pull your team's Cursor usage and spend data into the PostHog Data warehouse.

You need a Cursor team plan (Business or Enterprise). A team admin can create an API key in the [Cursor dashboard](https://cursor.com/dashboard) under Settings → Cursor Admin API Keys.
""",
            iconPath="/static/services/cursor.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/cursor",
            keywords=["ai", "code editor", "developer tools", "usage", "anysphere"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Admin API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="key_...",
                        secret=True,
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.cursor.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked Admin API key surfaces as a requests HTTPError when `_fetch`
            # calls `raise_for_status()`. Retrying can never satisfy a credential problem, so stop
            # the sync. Match the stable status text and base host, not the per-request path.
            f"401 Client Error: Unauthorized for url: {CURSOR_BASE_URL}": "Your Cursor Admin API key is invalid or has been revoked. Create a new key in your Cursor dashboard settings, then reconnect.",
            f"403 Client Error: Forbidden for url: {CURSOR_BASE_URL}": "Your Cursor Admin API key does not have access to this data. Admin API keys must be created by a team admin, and some endpoints require an Enterprise plan.",
        }

    def get_schemas(
        self,
        config: CursorSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = CURSOR_ENDPOINTS[endpoint]
            has_incremental = len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=endpoint_config.description,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: CursorSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_cursor_credentials(config.api_key):
            return True, None

        return False, "Invalid Cursor Admin API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CursorResumeConfig]:
        return ResumableSourceManager[CursorResumeConfig](inputs, CursorResumeConfig)

    def source_for_pipeline(
        self,
        config: CursorSourceConfig,
        resumable_source_manager: ResumableSourceManager[CursorResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return cursor_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
