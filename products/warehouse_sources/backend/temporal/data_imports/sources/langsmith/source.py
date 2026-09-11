from typing import Any, Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.langsmith import (
    LangSmithSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.langsmith import (
    DEFAULT_BASE_URL,
    PAGINATION_TOO_LARGE_ERROR,
    REPEATED_CURSOR_ERROR,
    RESPONSE_TOO_LARGE_ERROR,
    RETRYABLE_API_ERROR,
    RUNS_PAGE_TOO_LARGE_ERROR,
    LangSmithResumeConfig,
    langsmith_source,
    normalize_base_url,
    validate_credentials as validate_langsmith_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LANGSMITH_ENDPOINTS,
    RUNS_SELECT_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LangSmithSource(ResumableSource[LangSmithSourceConfig, LangSmithResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LANGSMITH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LANG_SMITH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="LangSmith",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter a LangSmith API key to sync your LLM traces, tracing projects, datasets, and feedback into the PostHog Data warehouse.

Create an API key in your [LangSmith settings](https://smith.langchain.com/settings) under **API Keys**.

Leave the **Host** field blank for the US cloud (`api.smith.langchain.com`). Set it to `https://eu.api.smith.langchain.com` for EU-region accounts, or to your own host for self-hosted deployments.""",
            iconPath="/static/services/langsmith.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/langsmith",
            keywords=["llm", "observability", "tracing", "langchain", "evals"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="lsv2_pt_...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="host",
                        label="Host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://api.smith.langchain.com",
                        secret=False,
                    ),
                ],
            ),
        )

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key is sent to `host`; retargeting it must re-require the key so a preserved
        # secret can't be redirected at a server the editor controls.
        return ["host"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # LangSmith rejects the request itself — a filter or parameter its deployment doesn't
            # accept — rather than the credentials. The request shape is fixed per endpoint, so
            # every retry sends the identical query and is rejected identically. `_fetch_page`
            # logs the response body, which is the only place the vendor's reason survives.
            "400 Client Error": "LangSmith rejected PostHog's request for this table. Check that the Host field matches your LangSmith region or deployment, then contact support if it keeps failing.",
            "401 Client Error": "Your LangSmith API key is invalid or has been revoked. Create a new API key in your LangSmith settings, then reconnect.",
            "403 Client Error": "Your LangSmith API key does not have access to this workspace. Check the key's workspace scope, then reconnect.",
            REPEATED_CURSOR_ERROR: "LangSmith kept returning the same pagination cursor, so the import was stopped to avoid looping. This usually means the host is misconfigured. Check the Host field, then reconnect.",
            RESPONSE_TOO_LARGE_ERROR: "A page of data from the LangSmith API exceeded 256 MB. This usually means individual records contain very large inputs or outputs. Contact PostHog support for next steps.",
            PAGINATION_TOO_LARGE_ERROR: "The LangSmith API returned more pagination data than PostHog can accept, so the import was stopped. This usually means the host is misconfigured. Check the Host field, then reconnect.",
            RUNS_PAGE_TOO_LARGE_ERROR: "A single LangSmith trace was too large to import, so the runs sync stopped. This usually means one trace has an unusually large input or output. Contact support so we can help unblock the sync.",
        }

    def get_retryable_errors(self) -> set[str]:
        # `_fetch_page` already retries a 429/5xx (the RETRYABLE_API_ERROR sentinel), a dropped
        # connection, and a read timeout up to 5 attempts. Once that budget exhausts, Temporal
        # retries the whole activity from the saved pagination checkpoint, so the failure is
        # transient and self-recovering. The host is customer-controlled (self-hosted LangSmith),
        # so match only the stable, host-independent parts of the message.
        return {
            RETRYABLE_API_ERROR,
            # A read timeout, plus the wrapper urllib3 puts around one it retried itself, which
            # leaves the timeout nested inside as the cause.
            "Read timed out",
            "Max retries exceeded with url",
            # A dropped connection arrives without that wrapper in both places it can happen. The
            # shared retry policy retries GET/HEAD/OPTIONS only, so urllib3 re-raises the drop bare
            # on the runs/query POST and requests reports "Connection aborted". A drop after the
            # headers, while `_read_capped_body` streams the body, is past the retry path already
            # and reports "Connection broken".
            "Connection aborted",
            "Connection broken",
        }

    def get_schemas(
        self,
        config: LangSmithSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "runs":
                return (
                    "Traces and their nested spans (LLM calls, chains, tools) across every tracing "
                    "project. The first incremental sync only pulls the last 365 days"
                )
            if endpoint == "projects":
                return "Tracing projects (called sessions in the LangSmith API)"
            return None

        def _schema_metadata(endpoint: str) -> dict[str, Any] | None:
            # Only runs has a fixed field list, so only runs can fill the column picker before it
            # has ever synced. Every other endpoint returns whatever fields the API sends.
            if endpoint != "runs":
                return None
            return {"columns": [{"name": name} for name in RUNS_SELECT_FIELDS]}

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = LANGSMITH_ENDPOINTS[endpoint]
            supports_incremental = endpoint_config.window_param is not None and bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=supports_incremental,
                supports_append=supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                detected_primary_keys=endpoint_config.primary_keys,
                description=_description(endpoint),
                schema_metadata=_schema_metadata(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: LangSmithSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_langsmith_credentials(config.api_key, config.host or None, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LangSmithResumeConfig]:
        return ResumableSourceManager[LangSmithResumeConfig](inputs, LangSmithResumeConfig)

    def source_for_pipeline(
        self,
        config: LangSmithSourceConfig,
        resumable_source_manager: ResumableSourceManager[LangSmithResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return langsmith_source(
            api_key=config.api_key,
            base_url=normalize_base_url(config.host or DEFAULT_BASE_URL),
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            # The generic projection drops unselected columns after the fetch, which is too late for
            # the response cap, so the runs endpoint also narrows its server-side `select`.
            enabled_columns=inputs.enabled_columns,
        )
