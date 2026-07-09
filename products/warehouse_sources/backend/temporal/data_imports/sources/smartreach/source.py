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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SmartreachSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.settings import (
    ENDPOINTS,
    SMARTREACH_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.smartreach import (
    SmartreachResumeConfig,
    check_access,
    smartreach_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SmartreachSource(ResumableSource[SmartreachSourceConfig, SmartreachResumeConfig]):
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
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — we deliberately do not use SmartReach's
        # newer_than/older_than filters, so there is no incremental cursor to advance.
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
        self, config: SmartreachSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The user key is account-wide, so a single probe validates access to every schema; there is
        # no per-endpoint scope to check.
        status, message = check_access(config.api_key)
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
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
