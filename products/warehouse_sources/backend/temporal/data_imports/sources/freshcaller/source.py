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
from products.warehouse_sources.backend.temporal.data_imports.sources.freshcaller.freshcaller import (
    FreshcallerResumeConfig,
    freshcaller_source,
    normalize_subdomain,
    validate_credentials as validate_freshcaller_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshcaller.settings import FRESHCALLER_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FreshcallerSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

# This first cut covers Freshcaller's top-level v1 list endpoints (Users, Teams, Calls, Call
# Metrics). Account-level data export is an asynchronous request/poll job rather than a list
# endpoint, and recording download/delete are per-call side endpoints — both are intentionally
# left out of this first cut. There is no webhook management API.

_SUBDOMAIN_REGEX = re.compile(r"^[a-zA-Z0-9-]+$")

# User-facing auth/permission messages, shared between sync-time (get_non_retryable_errors) and
# connect-time (validate_credentials) so the two can't drift.
_ERR_AUTH_FAILED = "Freshcaller authentication failed. Please check your API key and account name."
_ERR_FORBIDDEN = "Your Freshcaller API key does not have permission for this resource. Check the agent's role/scope."


@SourceRegistry.register
class FreshcallerSource(ResumableSource[FreshcallerSourceConfig, FreshcallerResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FRESHCALLER

    @property
    def connection_host_fields(self) -> list[str]:
        # Freshcaller's connection target is the account subdomain, not a `host` field. Editing it
        # on an existing source must force the API key to be re-entered.
        return ["subdomain"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.freshcaller.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": _ERR_AUTH_FAILED,
            "403 Client Error: Forbidden for url": _ERR_FORBIDDEN,
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FRESHCALLER,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Freshcaller",
            caption="""Enter your Freshcaller account name and API key to pull your Freshcaller call-center data into the PostHog Data warehouse.

Your **account name** is the subdomain in your Freshcaller URL — e.g. `acme` for `acme.freshcaller.com`.

Your **API key** is on your Freshcaller profile settings page (click your profile picture → **Profile settings**; the API key is shown in the right sidebar).""",
            iconPath="/static/services/freshcaller.png",
            docsUrl="https://posthog.com/docs/cdp/sources/freshcaller",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Freshcaller account name",
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
        config: FreshcallerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=name,
                # Only Calls / Call Metrics expose a server-side `by_time` window; the rest are
                # full refresh only.
                supports_incremental=endpoint.supports_incremental,
                supports_append=endpoint.supports_incremental,
                incremental_fields=endpoint.incremental_fields,
                detected_primary_keys=["id"],
            )
            for name, endpoint in FRESHCALLER_ENDPOINTS.items()
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: FreshcallerSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not _SUBDOMAIN_REGEX.match(normalize_subdomain(config.subdomain)):
            return False, "Freshcaller account name is invalid"

        status = validate_freshcaller_credentials(config.subdomain, config.api_key)

        if status == 200:
            return True, None

        # A valid key that simply lacks scope for the probe endpoint returns 403. Accept it at
        # source-create (schema_name is None) — users may only grant the scopes they want to sync.
        if status == 403 and schema_name is None:
            return True, None

        if status == 403:
            return False, _ERR_FORBIDDEN

        if status == 401:
            return False, _ERR_AUTH_FAILED

        return False, "Could not connect to Freshcaller. Please check your account name and API key."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FreshcallerResumeConfig]:
        return ResumableSourceManager[FreshcallerResumeConfig](inputs, FreshcallerResumeConfig)

    def source_for_pipeline(
        self,
        config: FreshcallerSourceConfig,
        resumable_source_manager: ResumableSourceManager[FreshcallerResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return freshcaller_source(
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
