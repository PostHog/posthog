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
from products.warehouse_sources.backend.temporal.data_imports.sources.float_app.float_app import (
    FloatAppResumeConfig,
    float_app_source,
    validate_credentials as validate_float_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.float_app.settings import (
    ENDPOINTS,
    FLOAT_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FloatAppSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FloatAppSource(ResumableSource[FloatAppSourceConfig, FloatAppResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FLOATAPP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FLOAT_APP,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Float",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Float access token to automatically pull your Float resource-management data into the PostHog Data warehouse.

You can create an access token in Float under **Team Settings → Integrations → API**. The token has the same access as its account owner.

All streams sync via full refresh — Float's API exposes no server-side modified-since filter on its core resources.""",
            keywords=["resource management", "scheduling", "capacity planning"],
            iconPath="/static/services/float_app.png",
            docsUrl="https://posthog.com/docs/cdp/sources/float-app",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.float_app.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked Float token surfaces as an HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never satisfy a credential problem, so stop the sync.
            # Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.float.com": "Your Float access token is invalid or has been revoked. Create a new token in Float under Team Settings → Integrations → API, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.float.com": "Your Float access token does not have permission to sync this data. Confirm the token's account owner has access, then reconnect.",
        }

    def get_schemas(
        self,
        config: FloatAppSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = FLOAT_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                # Float has no server-side incremental filter today, so every stream is full refresh.
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
        self, config: FloatAppSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        ok, status_code = validate_float_credentials(config.api_key)
        if ok:
            return True, None
        if status_code == 401:
            return False, "Invalid Float access token"
        return False, "Could not connect to Float with the provided access token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FloatAppResumeConfig]:
        return ResumableSourceManager[FloatAppResumeConfig](inputs, FloatAppResumeConfig)

    def source_for_pipeline(
        self,
        config: FloatAppSourceConfig,
        resumable_source_manager: ResumableSourceManager[FloatAppResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return float_app_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
