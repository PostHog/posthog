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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ScalewaySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.scaleway.scaleway import (
    ScalewayResumeConfig,
    probe_endpoint,
    scaleway_source,
    validate_credentials as validate_scaleway_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.scaleway.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SCALEWAY_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ScalewaySource(ResumableSource[ScalewaySourceConfig, ScalewayResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SCALEWAY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SCALEWAY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Scaleway",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Scaleway API secret key and Organization ID to pull your Scaleway data into the PostHog Data warehouse.

Create an API key from the [IAM > API keys](https://console.scaleway.com/iam/api-keys) page in the Scaleway console, and find your Organization ID under [Organization settings](https://console.scaleway.com/organization/settings).

Grant the key the read permission sets for the data you want to sync, for example:
- `IAMReadOnly` for users, applications, groups, policies, API keys and SSH keys
- `ProjectReadOnly` for projects
- `BillingReadOnly` for invoices
- `AuditTrailReadOnly` for audit trail events
- `InstancesReadOnly` for instance servers
""",
            iconPath="/static/services/scaleway.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/scaleway",
            keywords=["cloud", "billing", "infrastructure", "invoices", "iam"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="secret_key",
                        label="API secret key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="organization_id",
                        label="Organization ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="00000000-0000-0000-0000-000000000000",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.scaleway.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid/revoked secret key surfaces as a requests HTTPError from raise_for_status().
            # Retrying can never satisfy a credential problem, so stop the sync. Match the stable
            # status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.scaleway.com": "Your Scaleway API secret key is invalid or has been revoked. Create a new key in the Scaleway console and reconnect.",
            "403 Client Error: Forbidden for url: https://api.scaleway.com": "Your Scaleway API key is missing the read permission set needed to sync this data. Grant the matching read permissions in the Scaleway console and reconnect.",
        }

    def get_schemas(
        self,
        config: ScalewaySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = SCALEWAY_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                # Full refresh only — no verified server-side "updated since" filter across endpoints.
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=endpoint_config.description,
                detected_primary_keys=endpoint_config.primary_keys,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: ScalewaySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not config.organization_id:
            return False, "Organization ID is required"

        if schema_name is None or schema_name not in SCALEWAY_ENDPOINTS:
            status = validate_scaleway_credentials(config.secret_key, config.organization_id)
            # Accept 403 at source-create: the token is genuine but may only be scoped to the
            # endpoints the user actually wants to sync. Per-table scope is surfaced separately.
            if status in (200, 403):
                return True, None
            if status == 401:
                return False, "Invalid Scaleway API secret key"
            return False, f"Could not validate Scaleway credentials (HTTP {status})"

        status = probe_endpoint(config.secret_key, config.organization_id, schema_name)
        if status == 200:
            return True, None
        if status == 401:
            return False, "Invalid Scaleway API secret key"
        if status == 403:
            return False, f"Your API key is missing the read permission set required to sync '{schema_name}'"
        return False, f"Could not validate access to '{schema_name}' (HTTP {status})"

    def get_endpoint_permissions(
        self, config: ScalewaySourceConfig, team_id: int, endpoints: list[str]
    ) -> dict[str, str | None]:
        # Only a genuine 403 denial marks a table as needing extra scopes; throttles, 5xx and network
        # blips are left reachable so a transient hiccup never blocks the picker.
        result: dict[str, str | None] = {}
        for name in endpoints:
            if name not in SCALEWAY_ENDPOINTS:
                result[name] = None
                continue
            status = probe_endpoint(config.secret_key, config.organization_id, name)
            result[name] = (
                "Requires a Scaleway API key with the matching read permission set" if status == 403 else None
            )
        return result

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ScalewayResumeConfig]:
        return ResumableSourceManager[ScalewayResumeConfig](inputs, ScalewayResumeConfig)

    def source_for_pipeline(
        self,
        config: ScalewaySourceConfig,
        resumable_source_manager: ResumableSourceManager[ScalewayResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return scaleway_source(
            secret_key=config.secret_key,
            organization_id=config.organization_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
