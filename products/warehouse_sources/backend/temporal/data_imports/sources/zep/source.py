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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ZepSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zep.settings import ENDPOINTS, ZEP_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.zep.zep import (
    ZepResumeConfig,
    validate_credentials as validate_zep_credentials,
    zep_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ZepSource(ResumableSource[ZepSourceConfig, ZepResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZEP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZEP,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Zep",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["agent memory", "llm", "knowledge graph", "ai"],
            caption="""Enter your Zep API key to sync your Zep agent-memory data into the PostHog Data warehouse.

You can create an API key in the [Zep dashboard](https://app.getzep.com/) under Project Settings. Keys are prefixed with `z_`.""",
            iconPath="/static/services/zep.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/zep",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="z_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.zep.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked Zep API key surfaces as an HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never satisfy a credential problem, so stop the sync.
            "401 Client Error: Unauthorized for url: https://api.getzep.com": "Your Zep API key is invalid or has been revoked. Create a new API key in your Zep dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.getzep.com": "Your Zep API key does not have access to this data. Check the key's permissions in your Zep dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: ZepSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Zep exposes no server-side timestamp filter (no created_since / updated_since), so every
        # endpoint is full-refresh only. See settings.py / the source docs for the rationale.
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = ZEP_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
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
        self, config: ZepSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_zep_credentials(config.api_key):
            return True, None

        return False, "Invalid Zep API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ZepResumeConfig]:
        return ResumableSourceManager[ZepResumeConfig](inputs, ZepResumeConfig)

    def source_for_pipeline(
        self,
        config: ZepSourceConfig,
        resumable_source_manager: ResumableSourceManager[ZepResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return zep_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
