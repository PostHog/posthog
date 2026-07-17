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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ZendutySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zenduty.settings import (
    ENDPOINTS,
    ZENDUTY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zenduty.zenduty import (
    ZendutyResumeConfig,
    probe_credentials,
    zenduty_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ZendutySource(ResumableSource[ZendutySourceConfig, ZendutyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://apidocs.zenduty.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZENDUTY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZENDUTY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Zenduty",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Zenduty API key to automatically pull your Zenduty incident-management and on-call data into the PostHog Data warehouse.

Create an API key in your Zenduty account under **Account Settings → Access → API Keys** (account owners and admins only). The key is account-scoped and read access is enough for syncing.""",
            iconPath="/static/services/zenduty.png",
            docsUrl="https://posthog.com/docs/cdp/sources/zenduty",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.zenduty.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Zenduty returns 403 (not 401) with `{"error": "Invalid or Inactive Token"}` for a bad token,
        # which surfaces as a requests HTTPError when `_fetch_page` calls `raise_for_status()`. No retry
        # can satisfy a credential problem. Match the stable status text + base host, not the path/query.
        return {
            "403 Client Error: Forbidden for url: https://www.zenduty.com": "Your Zenduty API key is invalid or inactive. Create a new API key in your Zenduty account settings, then reconnect.",
            "401 Client Error: Unauthorized for url: https://www.zenduty.com": "Your Zenduty API key is invalid or inactive. Create a new API key in your Zenduty account settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: ZendutySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = ZENDUTY_ENDPOINTS[endpoint]
            # Full refresh only: Zenduty does not clearly document a universal server-side
            # updated-since filter, so we don't advertise incremental sync (a client-side cursor
            # that still walks every page is not incremental — it just costs the same as a full
            # refresh). Config resources are small and mutable state (incident status) is best
            # picked up by re-syncing.
            return SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: ZendutySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        status = probe_credentials(config.api_key)

        if status == 200:
            return True, None
        # Zenduty returns 403 for an invalid/inactive token (there is no 401 path), so a 403 here is
        # a genuine bad key rather than a valid-token-missing-scope situation.
        if status in (401, 403):
            return False, "Your Zenduty API key is invalid or inactive."
        return False, "Could not validate your Zenduty API key. Please check the key and try again."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ZendutyResumeConfig]:
        return ResumableSourceManager[ZendutyResumeConfig](inputs, ZendutyResumeConfig)

    def source_for_pipeline(
        self,
        config: ZendutySourceConfig,
        resumable_source_manager: ResumableSourceManager[ZendutyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return zenduty_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
