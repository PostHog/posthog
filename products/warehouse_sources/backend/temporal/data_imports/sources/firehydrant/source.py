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
from products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant.firehydrant import (
    FireHydrantResumeConfig,
    firehydrant_source,
    validate_credentials as validate_firehydrant_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant.settings import (
    ENDPOINTS,
    FIREHYDRANT_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FireHydrantSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FireHydrantSource(ResumableSource[FireHydrantSourceConfig, FireHydrantResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FIREHYDRANT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FIRE_HYDRANT,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="FireHydrant",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your FireHydrant API key to pull your incident management data into the PostHog Data warehouse.

You can create a bot token or personal API key in your [FireHydrant API keys settings](https://app.firehydrant.io/organizations/api_keys). Bot tokens are recommended for automation that isn't tied to a specific user.""",
            iconPath="/static/services/firehydrant.png",
            docsUrl="https://posthog.com/docs/cdp/sources/firehydrant",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
            # Retrying can never satisfy a credential problem, so stop the sync. Match the stable
            # status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.firehydrant.io": "Your FireHydrant API key is invalid or has been revoked. Create a new API key in your FireHydrant settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.firehydrant.io": "Your FireHydrant API key is missing the permissions needed to sync this data. Grant the required permissions in your FireHydrant settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: FireHydrantSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = FIREHYDRANT_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                # FireHydrant has no uniform server-side incremental cursor, so every endpoint is
                # full refresh only.
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                detected_primary_keys=endpoint_config.primary_keys,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: FireHydrantSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_firehydrant_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FireHydrantResumeConfig]:
        return ResumableSourceManager[FireHydrantResumeConfig](inputs, FireHydrantResumeConfig)

    def source_for_pipeline(
        self,
        config: FireHydrantSourceConfig,
        resumable_source_manager: ResumableSourceManager[FireHydrantResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return firehydrant_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
