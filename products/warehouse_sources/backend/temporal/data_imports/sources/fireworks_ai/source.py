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
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.fireworks_ai import (
    FireworksAIResumeConfig,
    fireworks_ai_source,
    validate_credentials as validate_fireworks_ai_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FireworksAISourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FireworksAISource(ResumableSource[FireworksAISourceConfig, FireworksAIResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FIREWORKSAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FIREWORKS_AI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Fireworks AI",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Fireworks AI API key and account ID to sync your Fireworks control-plane data into the PostHog Data warehouse.

You can create an API key in your [Fireworks AI dashboard](https://fireworks.ai/settings/users/api-keys), and your account ID is shown in the same account settings.""",
            iconPath="/static/services/fireworks_ai.png",
            docsUrl="https://posthog.com/docs/cdp/sources/fireworks-ai",
            keywords=["llm", "inference", "fine-tuning", "ai"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-account",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="fw_...",
                        secret=True,
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked key returns 401; a valid key missing scope for a resource returns
            # 403. Neither is fixable by retrying, so stop the sync. Match the stable status text and
            # base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.fireworks.ai": "Your Fireworks AI API key is invalid or has been revoked. Create a new key in your Fireworks AI account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.fireworks.ai": "Your Fireworks AI API key is missing the permissions needed to sync this data. Grant the required access in your Fireworks AI account settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: FireworksAISourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Fireworks control-plane resources are mutable (job state, deployment state, model metadata
        # all change over their lifetime) and the list endpoints expose no confirmed server-side
        # timestamp filter, so every table is full refresh. Pagination is still resumable via
        # pageToken, so a run that heartbeat-times-out picks back up mid-collection.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: FireworksAISourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        ok, status = validate_fireworks_ai_credentials(config.api_key, config.account_id)
        if ok:
            return True, None

        # A valid token missing scope for a resource (403) must not block source creation — the user
        # may only intend to sync tables they do have access to. Re-raise it only when probing a
        # specific schema. Sync-time 403s are handled by get_non_retryable_errors().
        if status == 403 and schema_name is None:
            return True, None

        if status == 401:
            return False, "Invalid Fireworks AI API key"
        if status == 403:
            return False, "Your Fireworks AI API key is missing the permissions required for this table"

        return False, "Could not connect to Fireworks AI. Check your API key and account ID."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FireworksAIResumeConfig]:
        return ResumableSourceManager[FireworksAIResumeConfig](inputs, FireworksAIResumeConfig)

    def source_for_pipeline(
        self,
        config: FireworksAISourceConfig,
        resumable_source_manager: ResumableSourceManager[FireworksAIResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return fireworks_ai_source(
            api_key=config.api_key,
            account_id=config.account_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
