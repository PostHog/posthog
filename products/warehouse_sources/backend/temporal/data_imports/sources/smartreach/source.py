from typing import Optional, cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartreach import (
    SmartreachSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SMARTREACH_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.smartreach import (
    SMARTREACH_API_V1,
    SMARTREACH_API_V3,
    SmartreachResumeConfig,
    check_access,
    smartreach_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SmartreachSource(ResumableSource[SmartreachSourceConfig, SmartreachResumeConfig]):
    supported_versions = (SMARTREACH_API_V1, SMARTREACH_API_V3)
    default_version = SMARTREACH_API_V3
    api_docs_url = "https://help.smartreach.io/reference/using-the-smartreach-api"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SMARTREACH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SMARTREACH,
            category=DataWarehouseSourceCategory.SALES,
            label="Smartreach",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your SmartReach API key to pull your SmartReach data into the PostHog Data warehouse.

You can find your API key under **Settings → Integrations** in the [SmartReach app](https://app.smartreach.io/). The key is scoped to your user and grants read access to your prospects and campaigns.

Your team ID is required by the current SmartReach API. Find it in your SmartReach team settings; it starts with `team_`.
""",
            iconPath="/static/services/smartreach.png",
            docsUrl="https://posthog.com/docs/cdp/sources/smartreach",
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
                    # Optional at the form level so pre-existing v1 sources (stored without it) still
                    # load; validate_credentials requires it when the resolved version is v3.
                    SourceFieldInputConfig(
                        name="team_id",
                        label="Team ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="team_...",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked user key surfaces as a requests HTTPError when `_fetch_page`
            # calls `raise_for_status()`. Retrying can never satisfy a credential problem, so stop
            # the sync. Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.smartreach.io": "Your SmartReach API key is invalid or has been revoked. Generate a new key under Settings → Integrations, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.smartreach.io": "Your SmartReach API key does not have access to this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: SmartreachSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # The table set (prospects, campaigns) is identical across v1 and v3, so discovery does not
        # branch on api_version. Every endpoint is full refresh only — we deliberately do not use
        # SmartReach's newer_than/older_than filters, so there is no incremental cursor to advance
        # (INCREMENTAL_FIELDS is empty, so build_endpoint_schemas marks all endpoints full-refresh).
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: SmartreachSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        resolved_version = self.resolve_api_version(api_version)
        if resolved_version == SMARTREACH_API_V3 and not config.team_id:
            return False, "Enter your SmartReach team ID. The current SmartReach API needs it to return your data."
        # The user key is account-wide, so a single probe validates access to every schema; there is
        # no per-endpoint scope to check.
        status, message = check_access(config.api_key, resolved_version, config.team_id)
        if status == 200:
            return True, None
        if status in (401, 403):
            return False, "Invalid SmartReach API key"
        return False, message or "Could not validate SmartReach API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SmartreachResumeConfig]:
        return ResumableSourceManager[SmartreachResumeConfig](inputs, SmartreachResumeConfig)

    def source_for_pipeline(
        self,
        config: SmartreachSourceConfig,
        resumable_source_manager: ResumableSourceManager[SmartreachResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in SMARTREACH_ENDPOINTS:
            raise ValueError(f"Unknown SmartReach schema '{inputs.schema_name}'")

        return smartreach_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            api_version=self.resolve_api_version(inputs.api_version),
            smartreach_team_id=config.team_id,
            db_incremental_field_last_value=None,  # every SmartReach endpoint is full refresh
        )
