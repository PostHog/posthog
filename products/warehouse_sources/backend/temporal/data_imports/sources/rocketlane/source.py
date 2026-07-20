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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RocketlaneSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.rocketlane import (
    RocketlaneResumeConfig,
    check_access,
    rocketlane_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.settings import (
    ENDPOINTS,
    ROCKETLANE_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RocketlaneSource(ResumableSource[RocketlaneSourceConfig, RocketlaneResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("1.0",)
    default_version = "1.0"
    api_docs_url = "https://developer.rocketlane.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ROCKETLANE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ROCKETLANE,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Rocketlane",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Rocketlane API key to pull your Rocketlane data into the PostHog Data warehouse.

You can generate an API key under **Settings → API** in the [Rocketlane app](https://app.rocketlane.com/). This single key grants read access to your projects, tasks, time entries, users, and fields.
""",
            iconPath="/static/services/rocketlane.png",
            docsUrl="https://posthog.com/docs/cdp/sources/rocketlane",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked api-key surfaces as a requests HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never satisfy a credential problem, so stop the sync.
            # Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.rocketlane.com": "Your Rocketlane API key is invalid or has been revoked. Generate a new key under Settings → API, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.rocketlane.com": "Your Rocketlane API key does not have access to this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: RocketlaneSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — Rocketlane's list endpoints expose per-field filters
        # but no single server-side `updated_after` cursor, so there is nothing to advance.
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
        self, config: RocketlaneSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The api-key is account-wide, so a single probe validates access to every schema; there is
        # no per-endpoint scope to check.
        status, message = check_access(config.api_key)
        if status == 200:
            return True, None
        if status in (401, 403):
            return False, "Invalid Rocketlane API key"
        return False, message or "Could not validate Rocketlane API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RocketlaneResumeConfig]:
        return ResumableSourceManager[RocketlaneResumeConfig](inputs, RocketlaneResumeConfig)

    def source_for_pipeline(
        self,
        config: RocketlaneSourceConfig,
        resumable_source_manager: ResumableSourceManager[RocketlaneResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in ROCKETLANE_ENDPOINTS:
            raise ValueError(f"Unknown Rocketlane schema '{inputs.schema_name}'")

        return rocketlane_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
