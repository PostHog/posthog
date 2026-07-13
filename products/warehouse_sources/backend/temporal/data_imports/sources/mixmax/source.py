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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MixMaxSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mixmax.mixmax import (
    MixmaxResumeConfig,
    mixmax_source,
    validate_credentials as validate_mixmax_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mixmax.settings import ENDPOINTS, MIXMAX_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MixMaxSource(ResumableSource[MixMaxSourceConfig, MixmaxResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MIXMAX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MIX_MAX,
            category=DataWarehouseSourceCategory.SALES,
            label="Mixmax",
            releaseStatus=ReleaseStatus.ALPHA,
            # Kept hidden while the source lands without live-API credential verification; flip off
            # (delete this) once it has synced end-to-end against a real Mixmax workspace.
            unreleasedSource=True,
            caption="""Enter your Mixmax API token to sync your Mixmax data into the PostHog Data warehouse.

Create an API token under **Settings ▸ Integrations ▸ API** in Mixmax. The token is scoped to the user that creates it, so it can only sync data that user can access.

API access requires a Growth+ or Enterprise plan with the API feature enabled on your workspace.""",
            iconPath="/static/services/mixmax.png",
            docsUrl="https://posthog.com/docs/cdp/sources/mixmax",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mixmax.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
            # Retrying can never satisfy a credential/permission problem, so stop the sync. Match the
            # stable status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.mixmax.com": "Your Mixmax API token is invalid or has been revoked. Create a new token under Settings ▸ Integrations ▸ API, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.mixmax.com": "Your Mixmax API token does not have access to this data, or API access is not enabled on your plan. Check your Mixmax plan and workspace API settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: MixMaxSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Mixmax exposes no server-side timestamp filter, so every endpoint is full refresh only.
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = MIXMAX_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                should_sync_default=endpoint_config.should_sync_default,
                description=endpoint_config.description,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: MixMaxSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_mixmax_credentials(config.api_key):
            return True, None

        return False, "Invalid Mixmax API token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MixmaxResumeConfig]:
        return ResumableSourceManager[MixmaxResumeConfig](inputs, MixmaxResumeConfig)

    def source_for_pipeline(
        self,
        config: MixMaxSourceConfig,
        resumable_source_manager: ResumableSourceManager[MixmaxResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return mixmax_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
