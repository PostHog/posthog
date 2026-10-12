from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.retellai import (
    RetellAISourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.retell_ai.retell_ai import (
    RetellAIResumeConfig,
    retell_ai_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.retell_ai.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    INCREMENTAL_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RetellAISource(ResumableSource[RetellAISourceConfig, RetellAIResumeConfig]):
    lists_tables_without_credentials = True
    # Retell versions individual endpoints: calls/chats use v3, agents/phone numbers use v2.
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://docs.retellai.com/api-references/list-calls"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RETELLAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.RETELLAI,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Retell AI",
            docsUrl="https://posthog.com/docs/cdp/sources/retell-ai",
            iconPath="/static/services/retell_ai.png",
            keywords=["voice", "ai agent", "calls", "phone"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="",
                        caption="Create an API key in your Retell AI workspace settings with read access to the tables you want to sync.",
                    )
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Retell AI API key is invalid or expired. Create a new key and reconnect.",
            "403 Client Error": "Your Retell AI API key cannot read this table. Check its permissions and reconnect.",
        }

    def validate_credentials(
        self,
        config: RetellAISourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config.api_key, schema_name, self.resolve_api_version(api_version))

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.retell_ai.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: RetellAISourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=INCREMENTAL_FIELDS)
        for schema in schemas:
            if schema.supports_incremental:
                schema.default_incremental_lookback_seconds = INCREMENTAL_LOOKBACK_SECONDS
        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RetellAIResumeConfig]:
        return ResumableSourceManager(inputs, RetellAIResumeConfig)

    def source_for_pipeline(
        self,
        config: RetellAISourceConfig,
        resumable_source_manager: ResumableSourceManager[RetellAIResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return retell_ai_source(
            config.api_key, inputs, resumable_source_manager, self.resolve_api_version(inputs.api_version)
        )
