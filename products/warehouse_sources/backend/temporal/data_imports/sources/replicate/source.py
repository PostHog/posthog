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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ReplicateSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.replicate.replicate import (
    ReplicateResumeConfig,
    replicate_source,
    validate_credentials as validate_replicate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.replicate.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    REPLICATE_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ReplicateSource(ResumableSource[ReplicateSourceConfig, ReplicateResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REPLICATE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.REPLICATE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Replicate",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["ml", "ai", "models", "inference"],
            caption="""Enter your Replicate API token to automatically pull your Replicate data into the PostHog Data warehouse.

You can create an API token in your [Replicate account settings](https://replicate.com/account/api-tokens).""",
            iconPath="/static/services/replicate.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/replicate",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="r8_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.replicate.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A missing/invalid/revoked token surfaces as an HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never fix a credential problem, so stop the sync.
            # Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.replicate.com": "Your Replicate API token is invalid or has been revoked. Create a new token in your Replicate account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.replicate.com": "Your Replicate API token does not have access to this data. Check the token's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: ReplicateSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "predictions":
                return (
                    "Input, output and logs of API-created predictions are removed by Replicate about "
                    "an hour after completion (data_removed=true); older rows carry metadata only."
                )
            if endpoint == "models":
                return "The full public Replicate model catalog, not only your own models. Off by default."
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = REPLICATE_ENDPOINTS[endpoint]
            has_incremental = endpoint_config.time_filter_param is not None
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                detected_primary_keys=endpoint_config.primary_keys,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: ReplicateSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_replicate_credentials(config.api_key):
            return True, None

        return False, "Invalid Replicate API token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ReplicateResumeConfig]:
        return ResumableSourceManager[ReplicateResumeConfig](inputs, ReplicateResumeConfig)

    def source_for_pipeline(
        self,
        config: ReplicateSourceConfig,
        resumable_source_manager: ResumableSourceManager[ReplicateResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return replicate_source(
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
