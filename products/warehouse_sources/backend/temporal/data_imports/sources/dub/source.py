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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dub.dub import (
    DubResumeConfig,
    check_endpoint_access,
    dub_source,
    validate_credentials as validate_dub_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dub.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PLAN_GATED_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dub import DubSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DubSource(ResumableSource[DubSourceConfig, DubResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://dub.co/docs/api-reference/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DUB

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your Dub API key is invalid or has been revoked. Please create a new key in your Dub workspace settings and reconnect.",
            "403 Client Error: Forbidden for url": "Your Dub API key doesn't have access to this resource. Events and payouts require a Dub Business plan or higher, and partner tables require a partner program.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.dub.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DubSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self, config: DubSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        # Per-schema check (from the incremental_fields action): confirm the key's plan
        # actually reaches that endpoint. At source-create, only probe the token itself.
        if schema_name is not None and schema_name in ENDPOINTS:
            reason = check_endpoint_access(config.api_key, schema_name)
            if reason is not None:
                return False, reason
            return True, None

        return validate_dub_credentials(config.api_key)

    def get_endpoint_permissions(
        self, config: DubSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        # Only probe the plan/program-gated endpoints; the rest are reachable with any
        # workspace key, and /events access is shared by all three event tables.
        permissions: dict[str, str | None] = dict.fromkeys(endpoints)
        event_access: str | None | bool = False  # False = not probed yet
        for endpoint in endpoints:
            if endpoint not in PLAN_GATED_ENDPOINTS:
                continue
            if endpoint.endswith("_events"):
                if event_access is False:
                    event_access = check_endpoint_access(config.api_key, endpoint)
                permissions[endpoint] = cast(str | None, event_access)
            else:
                permissions[endpoint] = check_endpoint_access(config.api_key, endpoint)
        return permissions

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DubResumeConfig]:
        return ResumableSourceManager[DubResumeConfig](inputs, DubResumeConfig)

    def source_for_pipeline(
        self,
        config: DubSourceConfig,
        resumable_source_manager: ResumableSourceManager[DubResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return dub_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DUB,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Dub",
            caption="Create a workspace API key in your Dub workspace under Settings > API Keys. Event tables (clicks, leads, sales) and payouts require a Dub Business plan or higher.",
            docsUrl="https://posthog.com/docs/cdp/sources/dub",
            iconPath="/static/services/dub.png",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["dub.co", "short links", "attribution", "affiliate"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Workspace API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="dub_xxxxxxxx",
                        secret=True,
                    ),
                ],
            ),
        )
