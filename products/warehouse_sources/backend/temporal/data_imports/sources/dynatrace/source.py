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
from products.warehouse_sources.backend.temporal.data_imports.sources.dynatrace.dynatrace import (
    DynatraceResumeConfig,
    check_endpoint_permissions,
    dynatrace_source,
    validate_credentials as validate_dynatrace_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynatrace.settings import (
    DYNATRACE_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DynatraceSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SCHEMA_DESCRIPTIONS: dict[str, str] = {
    "problems": "Only syncs the last 365 days on initial sync",
    "events": "Only syncs the last 30 days on initial sync; limited by your Dynatrace event retention",
    "audit_logs": "Only syncs the last 30 days on initial sync; requires audit logging to be enabled in the environment",
    "hosts": "Hosts active in the last 30 days",
    "services": "Services active in the last 30 days",
    "applications": "Applications active in the last 30 days",
    "process_groups": "Process groups active in the last 30 days",
    "slos": "Includes the current evaluation (status, error budget) of each SLO",
}


@SourceRegistry.register
class DynatraceSource(ResumableSource[DynatraceSourceConfig, DynatraceResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DYNATRACE

    @property
    def connection_host_fields(self) -> list[str]:
        # `environment_url` is where the stored API token is sent; retargeting it must re-require
        # the token.
        return ["environment_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DYNATRACE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Dynatrace",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["apm", "observability", "monitoring"],
            caption="""Enter your Dynatrace environment URL and an API access token to sync problems, events, entity inventory, audit logs, vulnerabilities, metric metadata, and SLOs into the PostHog Data warehouse.

The environment URL is where you open Dynatrace — for SaaS it looks like `https://abc12345.live.dynatrace.com`; for Managed it's `https://your-domain/e/your-environment-id`.

Create an [access token](https://docs.dynatrace.com/docs/manage/identity-access-management/access-tokens-and-oauth-clients/access-tokens) in Dynatrace and grant read scopes for the data you want to sync:
- `problems.read`
- `events.read`
- `entities.read`
- `auditLogs.read`
- `securityProblems.read`
- `metrics.read`
- `slo.read`
""",
            iconPath="/static/services/dynatrace.png",
            docsUrl="https://posthog.com/docs/cdp/sources/dynatrace",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="environment_url",
                        label="Environment URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://abc12345.live.dynatrace.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="dt0c01.…",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Dynatrace API token. Generate a new access token and reconnect.",
            "403 Client Error": "Your Dynatrace API token is missing the read scope required for this data. Grant the scope in Dynatrace and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.dynatrace.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DynatraceSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=DYNATRACE_ENDPOINTS[endpoint].supports_time_filter,
                supports_append=DYNATRACE_ENDPOINTS[endpoint].supports_time_filter,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=_SCHEMA_DESCRIPTIONS.get(endpoint),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: DynatraceSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_dynatrace_credentials(config.environment_url, config.api_token, team_id, schema_name)

    def get_endpoint_permissions(
        self, config: DynatraceSourceConfig, team_id: int, endpoints: list[str]
    ) -> dict[str, str | None]:
        # Dynatrace scopes are granted per API area, so per-table access varies with the token.
        # Probe each scope so the schema picker can flag tables the token can't read.
        return check_endpoint_permissions(config.environment_url, config.api_token, endpoints, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DynatraceResumeConfig]:
        return ResumableSourceManager[DynatraceResumeConfig](inputs, DynatraceResumeConfig)

    def source_for_pipeline(
        self,
        config: DynatraceSourceConfig,
        resumable_source_manager: ResumableSourceManager[DynatraceResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return dynatrace_source(
            environment_url=config.environment_url,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
