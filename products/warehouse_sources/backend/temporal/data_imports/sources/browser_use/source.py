from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use.browser_use import (
    BrowserUseResumeConfig,
    browser_use_source,
    validate_credentials as validate_browser_use_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use.settings import (
    BROWSER_USE_API_VERSION_V3,
    BROWSER_USE_API_VERSION_V4,
    endpoints_for_version,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.browseruse import (
    BrowserUseSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BrowserUseSource(ResumableSource[BrowserUseSourceConfig, BrowserUseResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # v3 was the experimental agent API; v4 is the current default. The two serve different table
    # sets (v4 drops the workspaces list and session_messages, adds runs, and reshapes sessions),
    # so new sources default to v4 while existing v3-pinned sources keep working unchanged.
    supported_versions = (BROWSER_USE_API_VERSION_V3, BROWSER_USE_API_VERSION_V4)
    default_version = BROWSER_USE_API_VERSION_V4
    api_docs_url = "https://docs.browser-use.com/cloud/api-reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BROWSERUSE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BROWSER_USE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Browser Use",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Browser Use API key to automatically pull your Browser Use Cloud data into the PostHog Data warehouse.

You can create a non-expiring API key at [cloud.browser-use.com/settings](https://cloud.browser-use.com/settings).""",
            iconPath="/static/services/browser_use.png",
            docsUrl="https://posthog.com/docs/cdp/sources/browser-use",
            keywords=["browser automation", "ai agents", "agent runs", "web automation"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="bu_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked key surfaces as a requests HTTPError from raise_for_status.
            # Retrying can never satisfy a credential problem, so stop the sync. Match the stable
            # status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.browser-use.com": "Your Browser Use API key is invalid or has been revoked. Create a new key at cloud.browser-use.com/settings, then reconnect.",
            # A 403 means the key is valid but lacks access to the resource; retrying can never
            # satisfy a permission problem, so surface it as terminal too.
            "403 Client Error: Forbidden for url: https://api.browser-use.com": "Your Browser Use API key does not have permission to access this Browser Use resource. Check the key permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: BrowserUseSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # No Browser Use list endpoint (either version) exposes a server-side since-filter or sort
        # parameter, so there is no reliable way to fetch only new rows. Every endpoint is therefore
        # full-refresh only (no incremental fields declared) — declaring incremental would advertise
        # a mode that still scans the whole list each run. The v3 and v4 table sets differ, so a
        # pinned source must discover under its own version: discovery diffs run under the source
        # pin and would orphan tables absent from the other version's catalog.
        catalog = endpoints_for_version(self.resolve_api_version(api_version))
        return build_endpoint_schemas(
            catalog.keys(),
            {},
            names,
            should_sync_default={
                endpoint: endpoint_config.should_sync_default for endpoint, endpoint_config in catalog.items()
            },
        )

    def validate_credentials(
        self,
        config: BrowserUseSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # Pre-creation calls pass no pin and resolve to default_version (what new rows are stamped
        # with); a pinned source revalidates against its own version's probe endpoint.
        if validate_browser_use_credentials(config.api_key, self.resolve_api_version(api_version)):
            return True, None

        return False, "Invalid Browser Use API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BrowserUseResumeConfig]:
        return ResumableSourceManager[BrowserUseResumeConfig](inputs, BrowserUseResumeConfig)

    def source_for_pipeline(
        self,
        config: BrowserUseSourceConfig,
        resumable_source_manager: ResumableSourceManager[BrowserUseResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        api_version = self.resolve_api_version(inputs.api_version)
        if inputs.schema_name not in endpoints_for_version(api_version):
            raise ValueError(f"Unknown Browser Use schema '{inputs.schema_name}' for API version {api_version}")

        return browser_use_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            api_version=api_version,
        )
