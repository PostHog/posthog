from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.assemblyai import (
    BASE_URLS,
    AssemblyAIResumeConfig,
    assemblyai_source,
    validate_credentials as validate_assemblyai_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.settings import (
    ASSEMBLYAI_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AssemblyAISourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AssemblyAISource(ResumableSource[AssemblyAISourceConfig, AssemblyAIResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ASSEMBLYAI

    @property
    def connection_host_fields(self) -> list[str]:
        # `region` picks the host the stored API key is sent to. Retargeting it must re-require the
        # secret so a preserved key can't be aimed at a different regional endpoint without re-entry.
        return ["region"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ASSEMBLY_AI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AssemblyAI",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption=(
                "Enter your AssemblyAI API key to sync your speech-to-text transcripts into the PostHog "
                "Data warehouse. Find your key in the [AssemblyAI dashboard](https://www.assemblyai.com/app/api-keys).\n\n"
                "Only transcripts created in the **last 90 days** are retained by AssemblyAI and available to sync."
            ),
            iconPath="/static/services/assemblyai.png",
            docsUrl="https://posthog.com/docs/cdp/sources/assemblyai",
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
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.assemblyai.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api.eu.assemblyai.com)", value="eu"),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # AssemblyAI returns 401 for a missing/invalid token. There's no scope/permission model, so a
        # 401 is always a credential problem retrying can't fix. Match the stable status text + host.
        # Derive from BASE_URLS so a newly added region stays covered without updating two places.
        user_message = "Your AssemblyAI API key is invalid or has been revoked. Create a new key in the AssemblyAI dashboard, then reconnect."
        return {f"401 Client Error: Unauthorized for url: {url}": user_message for url in BASE_URLS.values()}

    def get_schemas(
        self,
        config: AssemblyAISourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            return SourceSchema(
                name=endpoint,
                # No server-side `created >= X` filter exists, so an "incremental" sync would still
                # walk the whole list every run — ship full refresh only. See settings.py.
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=ASSEMBLYAI_ENDPOINTS[endpoint].should_sync_default,
                description="Lists transcripts and hydrates each with its full text, words, and audio-intelligence results. AssemblyAI retains only the last 90 days. Full refresh only.",
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: AssemblyAISourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_assemblyai_credentials(config.api_key, config.region):
            return True, None

        return False, "Invalid AssemblyAI API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AssemblyAIResumeConfig]:
        return ResumableSourceManager[AssemblyAIResumeConfig](inputs, AssemblyAIResumeConfig)

    def source_for_pipeline(
        self,
        config: AssemblyAISourceConfig,
        resumable_source_manager: ResumableSourceManager[AssemblyAIResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return assemblyai_source(
            api_key=config.api_key,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
