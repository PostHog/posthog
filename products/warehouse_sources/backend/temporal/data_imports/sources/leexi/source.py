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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.leexi import LeexiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.leexi.leexi import (
    LeexiResumeConfig,
    leexi_source,
    probe_endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.leexi.settings import (
    ENDPOINT_PROBE_PATHS,
    ENDPOINT_SCOPES,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LeexiSource(ResumableSource[LeexiSourceConfig, LeexiResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://docs.public-api.leexi.ai/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LEEXI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LEEXI,
            category=DataWarehouseSourceCategory.SALES,
            label="Leexi",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["notetaker", "call recording", "conversation intelligence", "transcription"],
            caption="""Enter a Leexi API key pair to pull your Leexi calls, notes, meeting events, users, and teams into the PostHog Data warehouse.

You can create an API key in Leexi under Settings > Company settings > API keys (requires an admin account).

Grant these permission scopes so every table can sync:
- `read_calls` (calls and call notes)
- `read_meeting_events`
- `read_users`
- `read_teams`
""",
            iconPath="/static/services/leexi.png",
            docsUrl="https://posthog.com/docs/cdp/sources/leexi",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key_id",
                        label="API key ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key_secret",
                        label="API key secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.leexi.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://public-api.leexi.ai": "Your Leexi API key is invalid or was revoked. Please create a new API key in Leexi and reconnect.",
            "402 Client Error: Payment Required for url: https://public-api.leexi.ai": "Your Leexi subscription is inactive. Please check your Leexi plan and try again.",
            "403 Client Error: Forbidden for url: https://public-api.leexi.ai": "Your Leexi API key is missing a required permission scope. Please grant the scopes listed in the connection form and try again.",
        }

    def get_schemas(
        self,
        config: LeexiSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            # call_notes fans out one request per call (50 requests/minute rate limit), and
            # most note content already rides on each call row — keep it opt-in.
            should_sync_default={"call_notes": False},
        )

    def validate_credentials(
        self, config: LeexiSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        probe_path = ENDPOINT_PROBE_PATHS.get(schema_name, "/users") if schema_name else "/users"
        status = probe_endpoint(config.api_key_id, config.api_key_secret, probe_path)

        if status == 200:
            return True, None
        if status == 401:
            return False, "Leexi API key is invalid. Please check the key ID and secret."
        if status == 402:
            return False, "Your Leexi subscription is inactive. Please check your Leexi plan."
        if status == 403:
            if schema_name is None:
                # The key authenticates but lacks the probe endpoint's scope. Users may
                # legitimately grant only the scopes for the tables they want to sync, so
                # don't block source creation — per-table scope status is surfaced in the
                # schema picker via get_endpoint_permissions.
                return True, None
            return False, f"Your Leexi API key is missing the `{ENDPOINT_SCOPES.get(schema_name)}` scope."
        return False, "Could not connect to the Leexi API. Please try again."

    def get_endpoint_permissions(
        self, config: LeexiSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        status_by_path: dict[str, Optional[int]] = {}
        permissions: dict[str, str | None] = {}
        for endpoint in endpoints:
            path = ENDPOINT_PROBE_PATHS.get(endpoint)
            if path is None:
                permissions[endpoint] = None
                continue
            if path not in status_by_path:
                status_by_path[path] = probe_endpoint(config.api_key_id, config.api_key_secret, path)
            status = status_by_path[path]
            # Only real denials count as missing scope — throttles, 5xx, and network blips
            # must not mark a table unreachable.
            if status == 403:
                permissions[endpoint] = f"API key is missing the `{ENDPOINT_SCOPES[endpoint]}` permission scope"
            elif status == 401:
                permissions[endpoint] = "API key is invalid"
            else:
                permissions[endpoint] = None
        return permissions

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LeexiResumeConfig]:
        return ResumableSourceManager[LeexiResumeConfig](inputs, LeexiResumeConfig)

    def source_for_pipeline(
        self,
        config: LeexiSourceConfig,
        resumable_source_manager: ResumableSourceManager[LeexiResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return leexi_source(
            api_key_id=config.api_key_id,
            api_key_secret=config.api_key_secret,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
