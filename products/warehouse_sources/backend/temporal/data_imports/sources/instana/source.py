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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import InstanaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.instana.instana import (
    PAGINATION_LIMIT_ERROR,
    RESPONSE_TOO_LARGE_ERROR,
    RESPONSE_TOO_SLOW_ERROR,
    InstanaHostNotAllowedError,
    InstanaResumeConfig,
    instana_source,
    validate_credentials as validate_instana_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instana.settings import (
    ENDPOINTS,
    EVENTS_DEFAULT_LOOKBACK_DAYS,
    INCREMENTAL_FIELDS,
    INSTANA_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class InstanaSource(ResumableSource[InstanaSourceConfig, InstanaResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INSTANA

    @property
    def connection_host_fields(self) -> list[str]:
        # The API token is sent to whatever host `base_url` points at, so retargeting it must
        # re-require the token (prevents credential exfiltration to another host).
        return ["base_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INSTANA,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="IBM Instana Observability",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["ibm", "apm", "observability", "monitoring"],
            caption="""Enter your Instana tenant URL and API token to pull your Instana data into the PostHog Data warehouse.

Your base URL is the address you use to open the Instana UI, e.g. `https://unit-tenant.instana.io` (or your self-hosted domain). Create an API token under **Settings → Team Settings → API Tokens**; the token's permission scopes control which tables can be synced.""",
            iconPath="/static/services/instana.png",
            docsUrl="https://posthog.com/docs/cdp/sources/instana",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="base_url",
                        label="Base URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://unit-tenant.instana.io",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.instana.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch` calls `raise_for_status()`.
            # Retrying can never fix a credential/permission problem, so fail the sync. The host is
            # per-tenant, so match only the stable status text.
            "401 Client Error: Unauthorized": "Your Instana API token is invalid or has been revoked. Create a new API token under Settings → Team Settings → API Tokens, then reconnect.",
            "403 Client Error: Forbidden": "Your Instana API token is missing the permission scopes needed to sync this data. Grant the required scopes on the token, then reconnect.",
            RESPONSE_TOO_LARGE_ERROR: "Instana returned a response that was too large to process. Please contact support if this persists.",
            RESPONSE_TOO_SLOW_ERROR: "Instana took too long to send a response. Check that the base URL points at a healthy Instana instance, then reconnect.",
            PAGINATION_LIMIT_ERROR: "Instana returned an unexpectedly large catalog that exceeded the pagination limit. Please contact support if this persists.",
        }

    def get_schemas(
        self,
        config: InstanaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = INSTANA_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                # Events mutate after creation (`state` and `end` change while an issue is open),
                # so append mode would materialize each update as a duplicate row — merge only.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=(
                    f"Only syncs the last {EVENTS_DEFAULT_LOOKBACK_DAYS} days on initial sync"
                    if endpoint == "events"
                    else None
                ),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: InstanaSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            ok, status_code = validate_instana_credentials(config.base_url, config.api_token, team_id)
        except (ValueError, InstanaHostNotAllowedError) as e:
            return False, str(e)

        if ok:
            return True, None
        if status_code == 401:
            return False, "Invalid Instana API token"
        # A 403 means the token is genuine but lacks the probed endpoint's scope — users may
        # legitimately only grant scopes for the tables they want to sync, so accept it at
        # source-create. Sync-time 403s are handled by `get_non_retryable_errors`.
        if status_code == 403:
            return True, None
        return False, "Could not connect to Instana with the provided base URL and API token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[InstanaResumeConfig]:
        return ResumableSourceManager[InstanaResumeConfig](inputs, InstanaResumeConfig)

    def source_for_pipeline(
        self,
        config: InstanaSourceConfig,
        resumable_source_manager: ResumableSourceManager[InstanaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return instana_source(
            base_url=config.base_url,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
