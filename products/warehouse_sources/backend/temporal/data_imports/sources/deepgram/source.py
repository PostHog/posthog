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
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.deepgram import (
    DeepgramResumeConfig,
    deepgram_source,
    validate_credentials as validate_deepgram_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DeepgramSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DeepgramSource(ResumableSource[DeepgramSourceConfig, DeepgramResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DEEPGRAM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DEEPGRAM,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Deepgram",
            caption="""Enter your Deepgram API key to automatically pull your Deepgram project data into the PostHog Data warehouse.

You can create an API key in the [Deepgram console](https://console.deepgram.com/) under **Settings** → **API keys**.

The key needs the following scopes to sync every table: `project:read`, `keys:read`, `members:read`, `billing:read`, and `usage:read` (a key with the `member` or `admin` role covers all of them).
""",
            iconPath="/static/services/deepgram.png",
            docsUrl="https://posthog.com/docs/cdp/sources/deepgram",
            keywords=["speech-to-text", "transcription", "voice ai", "usage"],
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
            unreleasedSource=True,
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.deepgram.com": "Your Deepgram API key is invalid or has been revoked. Create a new API key in the Deepgram console, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.deepgram.com": "Your Deepgram API key is missing the scopes needed to sync this data. Create a key with the `project:read`, `keys:read`, `members:read`, `billing:read`, and `usage:read` scopes, then reconnect.",
        }

    def get_schemas(
        self,
        config: DeepgramSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "requests":
                return "Per-request usage log across all projects, incremental on the request's created timestamp"
            if endpoint == "projects":
                return None
            return "Snapshot of the current state per project. Full refresh only"

        def _build_schema(endpoint: str) -> SourceSchema:
            incremental_fields = INCREMENTAL_FIELDS.get(endpoint, [])
            has_incremental = len(incremental_fields) > 0
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=incremental_fields,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: DeepgramSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_deepgram_credentials(config.api_key):
            return True, None

        return False, "Invalid Deepgram API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DeepgramResumeConfig]:
        return ResumableSourceManager[DeepgramResumeConfig](inputs, DeepgramResumeConfig)

    def source_for_pipeline(
        self,
        config: DeepgramSourceConfig,
        resumable_source_manager: ResumableSourceManager[DeepgramResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return deepgram_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
