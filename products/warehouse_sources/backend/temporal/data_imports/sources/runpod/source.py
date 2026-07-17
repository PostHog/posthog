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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RunPodSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.runpod.runpod import (
    RunPodResumeConfig,
    runpod_source,
    validate_credentials as validate_runpod_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.runpod.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    RUNPOD_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RunPodSource(ResumableSource[RunPodSourceConfig, RunPodResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.runpod.io/api-reference/overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RUNPOD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RUN_POD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="RunPod",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your RunPod API key to pull your GPU cloud infrastructure and billing history into the PostHog Data warehouse.

Create an API key in your [RunPod console settings](https://console.runpod.io/user/settings). A key with read permission is sufficient.""",
            iconPath="/static/services/runpod.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/runpod",
            keywords=["gpu", "cloud", "serverless", "billing"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="rpa_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.runpod.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://rest.runpod.io": "Your RunPod API key is invalid or has been revoked. Create a new API key in your RunPod console settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://rest.runpod.io": "Your RunPod API key does not have read access to this data. Update the key's permissions in your RunPod console settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: RunPodSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = RUNPOD_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_append,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                default_incremental_lookback_seconds=endpoint_config.default_incremental_lookback_seconds,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: RunPodSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_runpod_credentials(config.api_key):
            return True, None

        return False, "Invalid RunPod API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RunPodResumeConfig]:
        return ResumableSourceManager[RunPodResumeConfig](inputs, RunPodResumeConfig)

    def source_for_pipeline(
        self,
        config: RunPodSourceConfig,
        resumable_source_manager: ResumableSourceManager[RunPodResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return runpod_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
