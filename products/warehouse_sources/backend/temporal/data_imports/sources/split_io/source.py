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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SplitIoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.split_io.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SPLIT_IO_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.split_io.split_io import (
    SplitIoResumeConfig,
    split_io_source,
    validate_credentials as validate_split_io_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SplitIoSource(ResumableSource[SplitIoSourceConfig, SplitIoResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SPLITIO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SPLIT_IO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            keywords=["harness", "fme", "feature flags", "experimentation"],
            label="Split.io",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Split (Harness FME) Admin API key to pull your workspaces, environments, feature flags, segments, and change requests into the PostHog Data warehouse.

You can create an Admin API key in Split under **Admin settings → API keys** — choose the **Admin** type (client- and server-side SDK keys won't work). The key grants read access to every resource this source syncs.""",
            iconPath="/static/services/split_io.png",
            docsUrl="https://posthog.com/docs/cdp/sources/split-io",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Admin API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.split_io.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.split.io": "Your Split Admin API key is invalid or has been revoked. Create a new Admin API key under Admin settings → API keys, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.split.io": "Your Split API key does not have permission for this resource. Make sure the key is an Admin (org-scoped) API key, then reconnect.",
        }

    def get_schemas(
        self,
        config: SplitIoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # The Split Admin API exposes no server-side timestamp filter on these resources,
        # so every endpoint is full-refresh only (no incremental/append support).
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: SplitIoSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in SPLIT_IO_ENDPOINTS:
            return False, f"Unknown Split schema '{schema_name}'"

        status = validate_split_io_credentials(config.api_key, schema_name)

        if status is None:
            return False, "Could not reach the Split API. Please try again."
        if status == 401:
            return False, "Invalid Split Admin API key"
        # A valid key may legitimately lack scope for a specific endpoint. Accept 403 at
        # source-create (schema_name is None); only reject it for a specific schema check.
        if status == 403:
            if schema_name is None:
                return True, None
            return False, f"Your API key does not have permission to read '{schema_name}'"
        if status >= 400:
            return False, f"Split returned an unexpected status ({status})"
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SplitIoResumeConfig]:
        return ResumableSourceManager[SplitIoResumeConfig](inputs, SplitIoResumeConfig)

    def source_for_pipeline(
        self,
        config: SplitIoSourceConfig,
        resumable_source_manager: ResumableSourceManager[SplitIoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in SPLIT_IO_ENDPOINTS:
            raise ValueError(f"Unknown Split schema '{inputs.schema_name}'")

        return split_io_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
