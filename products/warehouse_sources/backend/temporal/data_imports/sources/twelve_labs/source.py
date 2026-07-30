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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TwelveLabsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_labs.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    TWELVE_LABS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_labs.twelve_labs import (
    TwelveLabsResumeConfig,
    twelve_labs_source,
    validate_credentials as validate_twelve_labs_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TwelveLabsSource(ResumableSource[TwelveLabsSourceConfig, TwelveLabsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v1.3",)
    default_version = "v1.3"
    api_docs_url = "https://docs.twelvelabs.io/v1.3/api-reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TWELVELABS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TWELVE_LABS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Twelve Labs",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Twelve Labs API key to sync your video understanding library into the PostHog Data warehouse.

You can create an API key in your [Twelve Labs dashboard](https://playground.twelvelabs.io/dashboard/api-key).""",
            iconPath="/static/services/twelve_labs.png",
            docsUrl="https://posthog.com/docs/cdp/sources/twelve-labs",
            keywords=["video", "ai", "video understanding", "indexing"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="tlk_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_labs.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A missing, invalid, or revoked API key surfaces as an HTTPError when `_fetch_page`
            # calls `raise_for_status()`. Retrying can never satisfy a credential problem, so stop
            # the sync. Match the stable status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.twelvelabs.io": "Your Twelve Labs API key is invalid or has been revoked. Create a new API key in your Twelve Labs dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.twelvelabs.io": "Your Twelve Labs API key does not have permission to access this data. Check the key's permissions in your Twelve Labs dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: TwelveLabsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = TWELVE_LABS_ENDPOINTS[endpoint]
            has_incremental = len(endpoint_config.incremental_fields) > 0
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: TwelveLabsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        ok, status_code = validate_twelve_labs_credentials(config.api_key)
        if ok:
            return True, None

        # Only a 401/403 means the key is genuinely bad. A 429/5xx or transport error is transient,
        # so tell the user to retry rather than telling them to replace a key that may be valid.
        if status_code in (401, 403):
            return False, "Invalid Twelve Labs API key"
        return False, "Could not connect to Twelve Labs. Check your connection and try again."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TwelveLabsResumeConfig]:
        return ResumableSourceManager[TwelveLabsResumeConfig](inputs, TwelveLabsResumeConfig)

    def source_for_pipeline(
        self,
        config: TwelveLabsSourceConfig,
        resumable_source_manager: ResumableSourceManager[TwelveLabsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return twelve_labs_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
