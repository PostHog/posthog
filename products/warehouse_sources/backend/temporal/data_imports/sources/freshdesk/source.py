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
from products.warehouse_sources.backend.temporal.data_imports.sources.freshdesk.freshdesk import (
    FreshdeskResumeConfig,
    freshdesk_source,
    normalize_subdomain,
    validate_credentials as validate_freshdesk_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshdesk.settings import FRESHDESK_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FreshdeskSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

# This first cut covers Freshdesk's top-level v2 endpoints only. Fan-out resources
# (ticket conversations, solution articles/folders/categories) and webhook-driven
# deltas are deliberately left out: Freshdesk has no documented public REST API for
# programmatic webhook management (webhooks are configured through admin automation
# rules), so they can't be wired up reliably without live verification.

_SUBDOMAIN_REGEX = re.compile(r"^[a-zA-Z0-9-]+$")


@SourceRegistry.register
class FreshdeskSource(ResumableSource[FreshdeskSourceConfig, FreshdeskResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FRESHDESK

    @property
    def connection_host_fields(self) -> list[str]:
        # Freshdesk's connection target is the subdomain, not a `host` field. Editing it on an
        # existing source must force the API key to be re-entered.
        return ["subdomain"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.freshdesk.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Freshdesk authentication failed. Please check your API key and domain.",
            "403 Client Error: Forbidden for url": "Your Freshdesk API key does not have permission for this resource. Check the agent's role/scope.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FRESHDESK,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Freshdesk",
            caption="""Enter your Freshdesk domain and API key to pull your Freshdesk support data into the PostHog Data warehouse.

Your **domain** is the subdomain in your Freshdesk URL — e.g. `acme` for `acme.freshdesk.com`.

Your **API key** is on your Freshdesk profile settings page (click your profile picture → **Profile settings**; the API key is shown in the right sidebar).""",
            iconPath="/static/services/freshdesk.png",
            docsUrl="https://posthog.com/docs/cdp/sources/freshdesk",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Freshdesk domain",
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
        config: FreshdeskSourceConfig,
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
            for name, endpoint in FRESHDESK_ENDPOINTS.items()
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: FreshdeskSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not _SUBDOMAIN_REGEX.match(normalize_subdomain(config.subdomain)):
            return False, "Freshdesk domain is invalid"

        status = validate_freshdesk_credentials(config.subdomain, config.api_key)

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
                "Your Freshdesk API key does not have permission for this resource. Check the agent's role/scope.",
            )

        if status == 401:
            return False, "Freshdesk authentication failed. Please check your API key and domain."

        return False, "Could not connect to Freshdesk. Please check your domain and API key."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FreshdeskResumeConfig]:
        return ResumableSourceManager[FreshdeskResumeConfig](inputs, FreshdeskResumeConfig)

    def source_for_pipeline(
        self,
        config: FreshdeskSourceConfig,
        resumable_source_manager: ResumableSourceManager[FreshdeskResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return freshdesk_source(
            api_key=config.api_key,
            subdomain=config.subdomain,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
