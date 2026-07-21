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
from products.warehouse_sources.backend.temporal.data_imports.sources.baseten.baseten import (
    BasetenResumeConfig,
    baseten_source,
    validate_credentials as validate_baseten_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.baseten.settings import (
    BASETEN_ENDPOINTS,
    ENDPOINTS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BasetenSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BasetenSource(ResumableSource[BasetenSourceConfig, BasetenResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BASETEN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BASETEN,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Baseten",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Baseten API key to sync your Baseten workspace data into the PostHog Data warehouse.

Create an API key in your [Baseten workspace settings](https://app.baseten.co/settings/api_keys). The key is workspace-scoped and read access to your models, deployments, chains, and training resources is sufficient.""",
            iconPath="/static/services/baseten.png",
            docsUrl="https://posthog.com/docs/cdp/sources/baseten",
            keywords=["ai", "inference", "ml", "gpu"],
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.baseten.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Baseten answers both a missing and an invalid API key with 403 PERMISSION_DENIED (it does
        # not use 401), so a 403 at sync time means the key is invalid or lacks access — retrying
        # can never fix that. Match the stable status text and base host, not the per-request path.
        return {
            "401 Client Error: Unauthorized for url: https://api.baseten.co": "Your Baseten API key is invalid or has been revoked. Create a new API key in your Baseten workspace settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.baseten.co": "Your Baseten API key is invalid or does not have access to this workspace data. Check the key in your Baseten workspace settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: BasetenSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Baseten exposes no server-side "updated since" filter on any entity list endpoint, so every
        # table syncs as a full refresh (no incremental fields).
        return build_endpoint_schemas(
            ENDPOINTS,
            {},
            names,
            should_sync_default={endpoint: BASETEN_ENDPOINTS[endpoint].should_sync_default for endpoint in ENDPOINTS},
        )

    def validate_credentials(
        self, config: BasetenSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_baseten_credentials(config.api_key):
            return True, None

        return False, "Invalid Baseten API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BasetenResumeConfig]:
        return ResumableSourceManager[BasetenResumeConfig](inputs, BasetenResumeConfig)

    def source_for_pipeline(
        self,
        config: BasetenSourceConfig,
        resumable_source_manager: ResumableSourceManager[BasetenResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return baseten_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
