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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LinearbSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.linearb.linearb import (
    LinearbResumeConfig,
    linearb_source,
    validate_credentials as validate_linearb_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linearb.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LINEARB_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LinearbSource(ResumableSource[LinearbSourceConfig, LinearbResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LINEARB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LINEARB,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="LinearB",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your LinearB API key to pull your engineering intelligence and DORA metrics into the PostHog Data warehouse.

Generate an API token from **Settings → API Tokens** in your [LinearB account](https://app.linearb.io/). The token grants access to your organization's teams, users, services, deployments, and computed metrics.

The **Measurements** table is only available on LinearB Business and Enterprise plans and is off by default — enable it if your plan includes API metrics access.""",
            iconPath="/static/services/linearb.png",
            docsUrl="https://posthog.com/docs/cdp/sources/linearb",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.linearb.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # LinearB's API gateway returns 403 for a missing, invalid, or revoked key (there is no
            # distinct 401). Retrying can never satisfy a credential problem, so stop the sync. Match
            # the stable status text and base host, not the per-request path/query.
            "403 Client Error: Forbidden for url: https://public-api.linearb.io": "Your LinearB API key is invalid, revoked, or lacks access to this data (the Measurements table needs a Business or Enterprise plan). Generate a new token in your LinearB account settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: LinearbSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "measurements":
                return (
                    "Organization-level Git/DORA metrics (cycle time, PR throughput, deploy frequency) "
                    "rolled up daily for the last 90 days. Requires a LinearB Business or Enterprise plan"
                )
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = LINEARB_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
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
        self,
        config: LinearbSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_linearb_credentials(config.api_key):
            return True, None

        return False, "Invalid LinearB API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LinearbResumeConfig]:
        return ResumableSourceManager[LinearbResumeConfig](inputs, LinearbResumeConfig)

    def source_for_pipeline(
        self,
        config: LinearbSourceConfig,
        resumable_source_manager: ResumableSourceManager[LinearbResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return linearb_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
