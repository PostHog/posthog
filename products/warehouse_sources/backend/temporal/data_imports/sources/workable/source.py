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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import WorkableSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.workable.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    WORKABLE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.workable.workable import (
    WorkableResumeConfig,
    validate_credentials as validate_workable_credentials,
    workable_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WorkableSource(ResumableSource[WorkableSourceConfig, WorkableResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WORKABLE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WORKABLE,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Workable",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Workable account subdomain and an SPI access token to pull your Workable recruiting data into the PostHog Data warehouse.

You can create an access token in your Workable account under **Settings > Integrations > Access Tokens** (admins only). Grant the following read scopes:
- `r_jobs`
- `r_candidates`
""",
            iconPath="/static/services/workable.png",
            docsUrl="https://posthog.com/docs/cdp/sources/workable",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Account subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="your-company",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored token is sent to https://<subdomain>.workable.com, so retargeting `subdomain`
        # must re-require the token to prevent exfiltration to an attacker-controlled host.
        return ["subdomain"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A bad/expired/revoked token surfaces as an HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Match the stable status text plus the per-account host prefix.
            "401 Client Error: Unauthorized for url: https://": "Your Workable access token is invalid or has expired. Create a new token in your Workable account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://": "Your Workable access token is missing the read scopes needed to sync this data (e.g. r_jobs, r_candidates). Grant them in your Workable account settings, then reconnect.",
            "Invalid Workable subdomain": "The Workable subdomain is invalid. Use just the account subdomain from https://<subdomain>.workable.com.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.workable.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: WorkableSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = WORKABLE_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: WorkableSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # Probe the specific schema's endpoint when given, otherwise a cheap `/jobs` probe.
        path = WORKABLE_ENDPOINTS[schema_name].path if schema_name in WORKABLE_ENDPOINTS else "/jobs"

        try:
            status_code, ok = validate_workable_credentials(config.subdomain, config.api_token, path)
        except ValueError as e:
            return False, str(e)

        if ok:
            return True, None
        if status_code == 401:
            return False, "Invalid Workable access token"
        if status_code == 403:
            # A 403 is a valid token missing a scope. At source-create (no schema_name) accept it —
            # users may only grant scopes for the endpoints they want. Reject it for a specific schema.
            if schema_name is None:
                return True, None
            return False, f"Your Workable access token is missing the scope required to sync '{schema_name}'"
        return False, "Unable to validate Workable credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WorkableResumeConfig]:
        return ResumableSourceManager[WorkableResumeConfig](inputs, WorkableResumeConfig)

    def source_for_pipeline(
        self,
        config: WorkableSourceConfig,
        resumable_source_manager: ResumableSourceManager[WorkableResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return workable_source(
            subdomain=config.subdomain,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
