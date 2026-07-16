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
from products.warehouse_sources.backend.temporal.data_imports.sources.e2b.e2b import (
    E2BResumeConfig,
    e2b_source,
    validate_credentials as validate_e2b_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.e2b.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import E2BSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class E2BSource(ResumableSource[E2BSourceConfig, E2BResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.E2B

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.E2_B,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="E2B",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your E2B API key to sync your sandbox infrastructure data into the PostHog Data warehouse.

You can create a team-scoped API key (prefixed `e2b_`) in your [E2B dashboard](https://e2b.dev/dashboard).""",
            iconPath="/static/services/e2b.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/e2b",
            keywords=["sandbox", "ai agents", "code execution", "infrastructure"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="e2b_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.e2b.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked API key surfaces as an HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never satisfy a credential problem, so stop the sync.
            "401 Client Error: Unauthorized for url: https://api.e2b.app": "Your E2B API key is invalid or has been revoked. Create a new team-scoped API key in your E2B dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.e2b.app": "Your E2B API key does not have access to this data. Check the key's team scope in your E2B dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: E2BSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every E2B list endpoint is a point-in-time inventory with no server-side timestamp filter,
        # so all are full refresh (no incremental / append).
        def _build_schema(endpoint: str) -> SourceSchema:
            return SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: E2BSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_e2b_credentials(config.api_key):
            return True, None

        return False, "Invalid E2B API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[E2BResumeConfig]:
        return ResumableSourceManager[E2BResumeConfig](inputs, E2BResumeConfig)

    def source_for_pipeline(
        self,
        config: E2BSourceConfig,
        resumable_source_manager: ResumableSourceManager[E2BResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return e2b_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
