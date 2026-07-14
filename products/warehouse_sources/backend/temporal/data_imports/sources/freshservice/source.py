import re
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
from products.warehouse_sources.backend.temporal.data_imports.sources.freshservice.freshservice import (
    FreshserviceResumeConfig,
    freshservice_source,
    normalize_domain,
    validate_credentials as validate_freshservice_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshservice.settings import (
    FRESHSERVICE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FreshserviceSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

# This first cut covers Freshservice's top-level v2 endpoints only. Fan-out resources
# (ticket conversations, solution articles/folders/categories) and webhook-driven deltas
# are deliberately left out: Freshservice has no documented public REST API for programmatic
# webhook management (webhooks are configured manually as Workflow Automator outbound web
# requests), so they can't be wired up reliably without live verification.

_DOMAIN_REGEX = re.compile(r"^[a-zA-Z0-9-]+$")


@SourceRegistry.register
class FreshserviceSource(ResumableSource[FreshserviceSourceConfig, FreshserviceResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FRESHSERVICE

    @property
    def connection_host_fields(self) -> list[str]:
        # Freshservice's connection target is the domain, not a `host` field. Editing it on an
        # existing source must force the API key to be re-entered.
        return ["domain"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.freshservice.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Freshservice authentication failed. Please check your API key and domain.",
            "403 Client Error: Forbidden for url": "Your Freshservice API key does not have permission for this resource. Check the agent's role/scope.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FRESHSERVICE,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Freshservice",
            caption="""Enter your Freshservice domain and API key to pull your Freshservice ITSM data into the PostHog Data warehouse.

Your **domain** is the subdomain in your Freshservice URL — e.g. `acme` for `acme.freshservice.com`.

Your **API key** is on your Freshservice profile settings page (click your profile picture → **Profile settings**; the API key is shown in the right sidebar).""",
            iconPath="/static/services/freshservice.png",
            docsUrl="https://posthog.com/docs/cdp/sources/freshservice",
            releaseStatus=ReleaseStatus.ALPHA,
            # Kept hidden while the connector's incremental/ordering behavior is verified against a
            # live Freshservice account. Drop this flag to release the source to users.
            unreleasedSource=True,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="domain",
                        label="Freshservice domain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="acme",
                        secret=False,
                    ),
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

    def get_schemas(
        self,
        config: FreshserviceSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=name,
                # Only the endpoints with a genuine server-side `updated_since` filter
                # support incremental sync; everything else is full refresh.
                supports_incremental=endpoint.updated_since_param is not None,
                supports_append=endpoint.updated_since_param is not None,
                incremental_fields=endpoint.incremental_fields,
            )
            for name, endpoint in FRESHSERVICE_ENDPOINTS.items()
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: FreshserviceSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not _DOMAIN_REGEX.match(normalize_domain(config.domain)):
            return False, "Freshservice domain is invalid"

        status = validate_freshservice_credentials(config.domain, config.api_key)

        if status == 200:
            return True, None

        # A valid key that simply lacks scope for the probe endpoint returns 403. Accept it at
        # source-create (schema_name is None) — users may only grant the scopes they want to sync.
        if status == 403 and schema_name is None:
            return True, None

        # schema_name is set: a 403 means the key lacks permission for this specific resource.
        if status == 403:
            return (
                False,
                "Your Freshservice API key does not have permission for this resource. Check the agent's role/scope.",
            )

        if status == 401:
            return False, "Freshservice authentication failed. Please check your API key and domain."

        return False, "Could not connect to Freshservice. Please check your domain and API key."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FreshserviceResumeConfig]:
        return ResumableSourceManager[FreshserviceResumeConfig](inputs, FreshserviceResumeConfig)

    def source_for_pipeline(
        self,
        config: FreshserviceSourceConfig,
        resumable_source_manager: ResumableSourceManager[FreshserviceResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return freshservice_source(
            api_key=config.api_key,
            domain=config.domain,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
