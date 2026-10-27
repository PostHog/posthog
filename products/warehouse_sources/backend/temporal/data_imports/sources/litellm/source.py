from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (
    DATABASE_HOST_NOT_ALLOWED_ERROR,
    HostNotAllowedError,
    ValidateDatabaseHostMixin,
    resolve_safe_host,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.litellm import (
    LiteLLMSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.litellm.litellm import (
    SPEND_LOGS_UNAVAILABLE_MESSAGE,
    LiteLLMResumeConfig,
    hostname_of,
    litellm_source,
    probe_key,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.litellm.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SPEND_LOGS_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LiteLLMSource(ResumableSource[LiteLLMSourceConfig, LiteLLMResumeConfig], ValidateDatabaseHostMixin):
    # Proxy-only signals: the `litellm` package alone means the SDK, which has no proxy to sync.
    codebase_detection = detect(env=("^LITELLM_MASTER_KEY$", "^LITELLM_PROXY_API_(KEY|BASE)$"))

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.litellm.ai/docs/proxy/cost_tracking"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LITELLM

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored key is sent to `base_url`, so retargeting it must re-require the key.
        return ["base_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LITELLM,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="LiteLLM",
            keywords=["llm proxy", "llm gateway", "llm spend"],
            caption="""Sync spend logs, keys, users, teams and models from your LiteLLM proxy into the PostHog Data warehouse.

Enter the proxy's public https URL and the master key or an admin key. A key without admin rights only syncs its own spend logs.""",
            iconPath="/static/services/litellm.png",
            docsUrl="https://posthog.com/docs/cdp/sources/litellm",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="base_url",
                        label="Proxy URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://litellm.example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Master or admin key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk-...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.litellm.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "LiteLLM rejected the key. Update the key on this source, then sync again.",
            "403 Client Error: Forbidden for url": "The LiteLLM key can't read this table. Use the master key or an admin key, then sync again.",
            SPEND_LOGS_UNAVAILABLE_MESSAGE: SPEND_LOGS_UNAVAILABLE_MESSAGE,
        }

    def get_schemas(
        self,
        config: LiteLLMSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # LiteLLM writes a spend log when the request ends, so a slow request lands behind the
        # watermark of faster ones that started later. The re-read window needs a merge to dedupe.
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            merge_only=("spend_logs",),
            default_incremental_lookback_seconds={"spend_logs": SPEND_LOGS_LOOKBACK_SECONDS},
        )

    def _check_host(self, config: LiteLLMSourceConfig, team_id: int) -> str | None:
        try:
            host_valid, host_error = self.is_database_host_valid(hostname_of(config.base_url), team_id)
        except ValueError:
            return "Enter the proxy URL as https://, for example https://litellm.example.com."
        return None if host_valid else (host_error or "That proxy URL is not allowed.")

    def validate_credentials(
        self,
        config: LiteLLMSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        host_error = self._check_host(config, team_id)
        if host_error is not None:
            return False, host_error
        status = probe_key(config.base_url, config.api_key)
        if status == 200:
            return True, None
        if status in (401, 403):
            return False, "LiteLLM rejected the key. Check the key and try again."
        return False, "Could not reach the LiteLLM proxy at that URL. Check the URL and that the proxy is public."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LiteLLMResumeConfig]:
        return ResumableSourceManager[LiteLLMResumeConfig](inputs, LiteLLMResumeConfig)

    def source_for_pipeline(
        self,
        config: LiteLLMSourceConfig,
        resumable_source_manager: ResumableSourceManager[LiteLLMResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        try:
            hostname = hostname_of(config.base_url)
        except ValueError as e:
            raise HostNotAllowedError(f"{DATABASE_HOST_NOT_ALLOWED_ERROR}: {e}") from e
        # A resolver failure raises TemporaryHostResolutionError and stays retryable.
        resolution = resolve_safe_host(hostname, inputs.team_id)
        if resolution.connect_host is None:
            raise HostNotAllowedError(f"{DATABASE_HOST_NOT_ALLOWED_ERROR}: {resolution.error}")
        return litellm_source(
            base_url=config.base_url,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
