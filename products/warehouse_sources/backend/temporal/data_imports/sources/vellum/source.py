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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import VellumSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vellum.settings import ENDPOINTS, VELLUM_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.vellum.vellum import (
    VellumResumeConfig,
    check_credentials,
    vellum_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class VellumSource(ResumableSource[VellumSourceConfig, VellumResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VELLUM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.VELLUM,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Vellum",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Vellum API key to sync your Vellum deployments, documents, and execution history into the PostHog Data warehouse.

You can create an API key in your Vellum [workspace settings](https://app.vellum.ai/api-keys). Vellum API keys are environment-scoped (Development / Staging / Production), so one key syncs one environment.""",
            iconPath="/static/services/vellum.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/vellum",
            keywords=["llm", "observability", "prompts", "workflows"],
            unreleasedSource=True,
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.vellum.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked Vellum API key surfaces as a 403 when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never satisfy a credential problem, so stop the sync.
            # Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.vellum.ai": "Your Vellum API key is invalid or has been revoked. Create a new key in your Vellum workspace settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.vellum.ai": "Your Vellum API key is invalid or missing the permissions needed to sync this data. Check the key in your Vellum workspace settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: VellumSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = VELLUM_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                # Vellum's list endpoints expose no server-side timestamp filter (a `created__gte`
                # cutoff is silently ignored), so every sync is a full refresh.
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: VellumSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        ok, status = check_credentials(config.api_key)
        if ok:
            return True, None
        if status in (401, 403):
            return False, "Invalid Vellum API key"
        return False, "Could not connect to Vellum. Please try again later."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[VellumResumeConfig]:
        return ResumableSourceManager[VellumResumeConfig](inputs, VellumResumeConfig)

    def source_for_pipeline(
        self,
        config: VellumSourceConfig,
        resumable_source_manager: ResumableSourceManager[VellumResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return vellum_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
