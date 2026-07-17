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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RenderSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.render.render import (
    RenderResumeConfig,
    render_source,
    validate_credentials as validate_render_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.render.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    RENDER_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RenderSource(ResumableSource[RenderSourceConfig, RenderResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://api-docs.render.com/reference/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RENDER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RENDER,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Render",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Render API key to pull your services, deploys, jobs, and databases into the PostHog Data warehouse.

You can create an API key in your [Render account settings](https://dashboard.render.com/settings#api-keys).

An API key grants access to every workspace your user belongs to. To sync a single workspace, set the optional workspace ID (found in your workspace settings, or via the `owners` table).
""",
            iconPath="/static/services/render.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/render",
            keywords=["cloud", "hosting", "deploys", "infrastructure"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="rnd_...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="owner_id",
                        label="Workspace ID (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="tea-...",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.render.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # An invalid or revoked Render API key surfaces as a requests HTTPError when
        # `_fetch_page` calls `raise_for_status()`. Retrying can never satisfy a credential
        # problem, so stop the sync. Match the stable status text and base host, not the
        # per-request path/query.
        return {
            "401 Client Error: Unauthorized for url: https://api.render.com": "Your Render API key is invalid or has been revoked. Create a new API key in your Render account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.render.com": "Your Render API key does not have access to this resource. Check the key's workspace access, then reconnect.",
        }

    def get_schemas(
        self,
        config: RenderSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = RENDER_ENDPOINTS[endpoint]
            has_incremental = bool(endpoint_config.incremental_fields)
            return SourceSchema(
                name=endpoint,
                # Events are immutable, so append-only is the only incremental-style sync mode;
                # every other resource mutates and needs merge semantics.
                supports_incremental=has_incremental and not endpoint_config.append_only,
                supports_append=has_incremental and endpoint_config.append_only,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: RenderSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_render_credentials(config.api_key):
            return True, None

        return False, "Invalid Render API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RenderResumeConfig]:
        return ResumableSourceManager[RenderResumeConfig](inputs, RenderResumeConfig)

    def source_for_pipeline(
        self,
        config: RenderSourceConfig,
        resumable_source_manager: ResumableSourceManager[RenderResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return render_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            owner_id=config.owner_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
