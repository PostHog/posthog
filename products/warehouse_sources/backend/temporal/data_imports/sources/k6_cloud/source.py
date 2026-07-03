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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import K6CloudSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.k6_cloud.k6_cloud import (
    K6CloudResumeConfig,
    k6_cloud_source,
    validate_credentials as validate_k6_cloud_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.k6_cloud.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    K6_CLOUD_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class K6CloudSource(ResumableSource[K6CloudSourceConfig, K6CloudResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.K6CLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.K6_CLOUD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Grafana Cloud k6",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Grafana Cloud k6 API token and stack ID to pull your load testing data into the PostHog Data warehouse.

Create a Personal API token (or use a Grafana Stack API token) and find your stack ID under **Testing & synthetics → Performance → Settings** in Grafana Cloud.""",
            iconPath="/static/services/k6_cloud.png",
            docsUrl="https://posthog.com/docs/cdp/sources/k6-cloud",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Personal or Stack API token",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="stack_id",
                        label="Stack ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="12345",
                        secret=False,
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.k6_cloud.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid/revoked token or wrong stack id surfaces as a requests HTTPError when
            # `fetch_page` calls `raise_for_status()`. Retrying can never fix a credential
            # problem, so stop the sync. Match the stable status text + base host, not the
            # per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.k6.io": "Your Grafana Cloud k6 API token is invalid or has been revoked. Create a new token, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.k6.io": "Your Grafana Cloud k6 API token does not have access to this data or stack. Check the token and stack ID, then reconnect.",
        }

    def get_schemas(
        self,
        config: K6CloudSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = K6_CLOUD_ENDPOINTS[endpoint]
            has_incremental = endpoint_config.time_filter_param is not None and bool(INCREMENTAL_FIELDS.get(endpoint))
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
        self, config: K6CloudSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        is_valid, is_forbidden = validate_k6_cloud_credentials(config.api_token, config.stack_id, schema_name)
        if is_valid:
            return True, None

        # A 403 at source-create means the token is genuine but lacks access to the probed
        # resource — accept it so users can still connect and pick the tables they can read.
        # For a specific schema the missing access is real, so reject it.
        if is_forbidden and schema_name is None:
            return True, None
        if is_forbidden:
            return False, f"Your k6 API token does not have access to the {schema_name} table"

        return False, "Invalid k6 API token or stack ID"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[K6CloudResumeConfig]:
        return ResumableSourceManager[K6CloudResumeConfig](inputs, K6CloudResumeConfig)

    def source_for_pipeline(
        self,
        config: K6CloudSourceConfig,
        resumable_source_manager: ResumableSourceManager[K6CloudResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return k6_cloud_source(
            api_token=config.api_token,
            stack_id=config.stack_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
