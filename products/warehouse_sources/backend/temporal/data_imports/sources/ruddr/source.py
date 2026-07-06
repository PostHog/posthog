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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RuddrSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ruddr.ruddr import (
    RuddrResumeConfig,
    check_access,
    ruddr_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ruddr.settings import ENDPOINTS, RUDDR_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RuddrSource(ResumableSource[RuddrSourceConfig, RuddrResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RUDDR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RUDDR,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Ruddr",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Ruddr API key to pull your professional services data into the PostHog Data warehouse.

You can create a workspace API key under **Settings → API Keys** in [Ruddr](https://www.ruddr.io). The key grants read access to your clients, projects, tasks, members, and time entries.
""",
            iconPath="/static/services/ruddr.png",
            docsUrl="https://posthog.com/docs/cdp/sources/ruddr",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.ruddr.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://www.ruddr.io": "Your Ruddr API key is invalid or has been revoked. Generate a new key under Settings → API Keys, then reconnect.",
            "403 Client Error: Forbidden for url: https://www.ruddr.io": "Your Ruddr API key does not have access to this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: RuddrSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — Ruddr's list endpoints expose no reliably ordered
        # server-side update timestamp, so there is no incremental cursor to advance.
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
        self, config: RuddrSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is workspace-wide, so a single probe validates access to every schema.
        status, message = check_access(config.api_key)
        if status == 200:
            return True, None
        if status in (401, 403):
            return False, "Invalid Ruddr API key"
        return False, message or "Could not validate Ruddr API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RuddrResumeConfig]:
        return ResumableSourceManager[RuddrResumeConfig](inputs, RuddrResumeConfig)

    def source_for_pipeline(
        self,
        config: RuddrSourceConfig,
        resumable_source_manager: ResumableSourceManager[RuddrResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in RUDDR_ENDPOINTS:
            raise ValueError(f"Unknown Ruddr schema '{inputs.schema_name}'")

        return ruddr_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
