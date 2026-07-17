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
    DEEPGRAM_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DeepgramSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DeepgramSource(ResumableSource[DeepgramSourceConfig, DeepgramResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://developers.deepgram.com/reference/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DEEPGRAM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DEEPGRAM,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Deepgram",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Deepgram API key to sync your Deepgram Management API data into the PostHog Data warehouse.

You can create an API key in your [Deepgram Console](https://console.deepgram.com/) under **Settings → API Keys**. A key with a read-capable scope (e.g. `member`) is sufficient — the source only reads projects, members, keys, balances, invites, and the request log.""",
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
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.deepgram.com": "Your Deepgram API key is invalid or has been revoked. Create a new key in your Deepgram Console, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.deepgram.com": "Your Deepgram API key is missing the scope needed to sync this data. Grant a read-capable scope in your Deepgram Console, then reconnect.",
        }

    def get_schemas(
        self,
        config: DeepgramSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = DEEPGRAM_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                detected_primary_keys=endpoint_config.primary_keys,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: DeepgramSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
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
