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
from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.elevenlabs import (
    ELEVENLABS_BASE_URL,
    ElevenLabsResumeConfig,
    elevenlabs_source,
    validate_credentials as validate_elevenlabs_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.settings import (
    ELEVENLABS_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ElevenLabsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ElevenLabsSource(ResumableSource[ElevenLabsSourceConfig, ElevenLabsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ELEVENLABS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ELEVEN_LABS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="ElevenLabs",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption=(
                "Enter your ElevenLabs API key to sync your speech generation history, conversational AI "
                "conversations and agents, voices, and models into the PostHog Data warehouse. Create a key under "
                "[Profile → API keys](https://elevenlabs.io/app/settings/api-keys).\n\n"
                "If the key uses restricted permissions, grant read access to the endpoints you want to sync: "
                "**History**, **Conversational AI**, **Voices**, **Models**, and **User** (used to verify the key)."
            ),
            iconPath="/static/services/elevenlabs.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/elevenlabs",
            keywords=["ai", "voice", "audio", "text-to-speech", "conversational ai"],
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            f"401 Client Error: Unauthorized for url: {ELEVENLABS_BASE_URL}": (
                "Your ElevenLabs API key is invalid, has been revoked, or lacks the permission for this endpoint. "
                "Check the key's permissions under Profile → API keys in ElevenLabs, then reconnect."
            ),
            f"403 Client Error: Forbidden for url: {ELEVENLABS_BASE_URL}": (
                "Your ElevenLabs API key does not have access to this endpoint. "
                "Check the key's permissions under Profile → API keys in ElevenLabs, then reconnect."
            ),
        }

    def get_schemas(
        self,
        config: ElevenLabsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=ELEVENLABS_ENDPOINTS[endpoint].incremental_param is not None,
                supports_append=ELEVENLABS_ENDPOINTS[endpoint].incremental_param is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=ELEVENLABS_ENDPOINTS[endpoint].schema_description,
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: ElevenLabsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_elevenlabs_credentials(config.api_key):
            return True, None

        return False, "Invalid ElevenLabs API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ElevenLabsResumeConfig]:
        return ResumableSourceManager[ElevenLabsResumeConfig](inputs, ElevenLabsResumeConfig)

    def source_for_pipeline(
        self,
        config: ElevenLabsSourceConfig,
        resumable_source_manager: ResumableSourceManager[ElevenLabsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return elevenlabs_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
