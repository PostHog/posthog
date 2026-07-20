from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HoneycombSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.honeycomb.honeycomb import (
    HoneycombResumeConfig,
    honeycomb_source,
    validate_credentials as validate_honeycomb_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.honeycomb.settings import (
    ENDPOINTS,
    HONEYCOMB_ENDPOINTS,
    INCREMENTAL_FIELDS,
    HoneycombScope,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HoneycombSource(ResumableSource[HoneycombSourceConfig, HoneycombResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("1",)  # v1 API, addressed via the /1/ URL path prefix
    default_version = "1"
    api_docs_url = "https://docs.honeycomb.io/api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HONEYCOMB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HONEYCOMB,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Honeycomb",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter a Honeycomb configuration API key to pull your Honeycomb observability configuration — datasets, SLOs, burn alerts, triggers, markers, boards, and more — into the PostHog Data warehouse.

You can create a configuration key under **Environment settings → API keys** in your [Honeycomb account](https://ui.honeycomb.io/). Grant read access for the resources you want to sync: Manage Queries and Columns, Manage SLOs, Manage Triggers, Manage Markers, Manage Boards, and Manage Recipients.

Keys are region-specific — pick the region that matches your Honeycomb account.""",
            iconPath="/static/services/honeycomb.png",
            docsUrl="https://posthog.com/docs/cdp/sources/honeycomb",
            keywords=["observability", "slo", "tracing"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Configuration API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Configuration key",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.honeycomb.io)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api.eu1.honeycomb.io)", value="eu"),
                        ],
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
        # No amount of retrying fixes a bad, revoked, or under-permissioned key, so stop the
        # sync. Match the stable status text and base host (one per region), not the
        # per-request path/query.
        return {
            "401 Client Error: Unauthorized for url: https://api.honeycomb.io": "Your Honeycomb API key is invalid, revoked, or for a different region. Create a configuration key in your Honeycomb environment settings, then reconnect.",
            "401 Client Error: Unauthorized for url: https://api.eu1.honeycomb.io": "Your Honeycomb API key is invalid, revoked, or for a different region. Create a configuration key in your Honeycomb environment settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.honeycomb.io": "Your Honeycomb API key is missing a permission needed to sync this data. Grant the matching access (e.g. Manage SLOs, Manage Triggers) on the key, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.eu1.honeycomb.io": "Your Honeycomb API key is missing a permission needed to sync this data. Grant the matching access (e.g. Manage SLOs, Manage Triggers) on the key, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.honeycomb.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: HoneycombSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            endpoint_config = HONEYCOMB_ENDPOINTS[endpoint]
            if endpoint == "recipients":
                return (
                    "Credential-bearing recipient fields (integration keys, webhook URLs and secrets) "
                    "are redacted during sync."
                )
            if endpoint_config.scope is HoneycombScope.PER_SLO:
                return "One row per burn alert per dataset, fetched by walking every dataset's SLOs."
            if endpoint_config.include_environment_wide:
                return "Includes environment-wide rows under the __all__ dataset slug alongside per-dataset rows."
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = HONEYCOMB_ENDPOINTS[endpoint]
            # Full refresh only: Honeycomb's v1 config endpoints expose no server-side
            # timestamp filter, so a client-side cursor would still walk every row each run.
            return SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: HoneycombSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_honeycomb_credentials(config.api_key, config.region)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HoneycombResumeConfig]:
        return ResumableSourceManager[HoneycombResumeConfig](inputs, HoneycombResumeConfig)

    def source_for_pipeline(
        self,
        config: HoneycombSourceConfig,
        resumable_source_manager: ResumableSourceManager[HoneycombResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return honeycomb_source(
            api_key=config.api_key,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
