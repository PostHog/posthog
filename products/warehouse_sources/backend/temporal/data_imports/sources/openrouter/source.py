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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OpenRouterSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.openrouter.openrouter import (
    OpenRouterResumeConfig,
    get_key_info,
    openrouter_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openrouter.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    OPENROUTER_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_MANAGEMENT_KEY_REQUIRED = (
    "Requires an OpenRouter management API key. This key is a regular inference key, which can only "
    "read the models and providers catalogs."
)

# The organization members and workspaces endpoints resolve only when the management key's account
# belongs to an OpenRouter organization; an account without one gets a 404. Retrying can't create an
# organization, so we stop and tell the customer.
_NO_ORGANIZATION = (
    "Your OpenRouter account isn't part of an organization, so the organization members and workspaces "
    "tables can't be synced. Disable these tables, or reconnect with a management key that belongs to an "
    "organization."
)


@SourceRegistry.register
class OpenRouterSource(ResumableSource[OpenRouterSourceConfig, OpenRouterResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPENROUTER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OPEN_ROUTER,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="OpenRouter",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your OpenRouter API key to pull your OpenRouter usage and account data into the PostHog Data warehouse.

Use a **management API key** (create one under [Settings -> Management Keys](https://openrouter.ai/settings/keys)) so the activity, API keys, credits, organization members, and workspaces tables can sync. A regular inference key can only read the models and providers catalogs.""",
            iconPath="/static/services/openrouter.png",
            docsUrl="https://posthog.com/docs/cdp/sources/openrouter",
            keywords=["llm", "ai gateway", "usage", "inference"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk-or-...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.openrouter.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A bad or revoked key surfaces as an HTTPError from `raise_for_status()`. Match the stable
            # status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://openrouter.ai": "Your OpenRouter API key is invalid or has been revoked. Create a new key in your OpenRouter dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://openrouter.ai": "Your OpenRouter API key is missing the management scope needed to sync this data. Use a management API key (Settings -> Management Keys), then reconnect.",
            # Match the org-scoped paths specifically, not a bare host 404, so a genuine bad path on
            # another endpoint still surfaces instead of being silently disabled. The query string is
            # dropped as the volatile part.
            "404 Client Error: Not Found for url: https://openrouter.ai/api/v1/organization/members": _NO_ORGANIZATION,
            "404 Client Error: Not Found for url: https://openrouter.ai/api/v1/workspaces": _NO_ORGANIZATION,
        }

    def get_schemas(
        self,
        config: OpenRouterSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "activity":
                return "Daily usage rollups; only the last 30 completed UTC days are available"
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            has_incremental = len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                # /activity re-fetches the (possibly partial) watermark day each run, so it relies on
                # merge to dedupe — append would materialize duplicates. Every other table is small
                # and full-refresh only.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=OPENROUTER_ENDPOINTS[endpoint].should_sync_default,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: OpenRouterSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        info = get_key_info(config.api_key)
        if info is None:
            return False, "Invalid OpenRouter API key. Create a key in your OpenRouter dashboard and try again."

        # At source-create (no schema_name) any genuine key is accepted — the catalog tables sync with
        # an inference key, and get_endpoint_permissions reports which tables need a management key.
        # When validating a specific management table, require the management scope.
        if schema_name is not None:
            endpoint = OPENROUTER_ENDPOINTS.get(schema_name)
            if endpoint is not None and endpoint.requires_management_key and not info.get("is_management_key"):
                return False, f"The '{schema_name}' table requires an OpenRouter management API key."

        return True, None

    def get_endpoint_permissions(
        self, config: OpenRouterSourceConfig, team_id: int, endpoints: list[str]
    ) -> dict[str, str | None]:
        info = get_key_info(config.api_key)
        # A None here is a transient /key failure, not a denial (the key was already validated at
        # create). Only a genuine 200 that reports a non-management key marks the management tables.
        if info is None:
            return dict.fromkeys(endpoints)

        is_management_key = bool(info.get("is_management_key"))

        result: dict[str, str | None] = {}
        for name in endpoints:
            endpoint = OPENROUTER_ENDPOINTS.get(name)
            if endpoint is not None and endpoint.requires_management_key and not is_management_key:
                result[name] = _MANAGEMENT_KEY_REQUIRED
            else:
                result[name] = None
        return result

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OpenRouterResumeConfig]:
        return ResumableSourceManager[OpenRouterResumeConfig](inputs, OpenRouterResumeConfig)

    def source_for_pipeline(
        self,
        config: OpenRouterSourceConfig,
        resumable_source_manager: ResumableSourceManager[OpenRouterResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return openrouter_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
