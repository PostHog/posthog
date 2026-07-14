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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LinodeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.linode.linode import (
    LinodeResumeConfig,
    linode_source,
    validate_credentials as validate_linode_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linode.settings import ENDPOINTS, LINODE_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LinodeSource(ResumableSource[LinodeSourceConfig, LinodeResumeConfig]):
    # get_schemas iterates the static ENDPOINTS catalog with no I/O, so the table list is safe to
    # render in public docs without credentials.
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LINODE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LINODE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Linode",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Linode (Akamai Connected Cloud) personal access token to pull your account data into the PostHog Data warehouse.

Create a personal access token in the [Linode Cloud Manager](https://cloud.linode.com/profile/tokens). Grant **read-only** access to the resources you want to sync:
- Account (invoices, payments, events, users)
- Linodes
- Volumes
- NodeBalancers
- Kubernetes
- Domains
""",
            iconPath="/static/services/linode.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/linode",
            keywords=["cloud", "infrastructure", "hosting", "akamai"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            # Kept hidden until the sync logic has been exercised against a live account (we could not
            # curl-verify the incremental X-Filter behavior without credentials).
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.linode.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A revoked/invalid token surfaces as a requests HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never satisfy a credential problem. Match the stable
            # status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.linode.com": "Your Linode API token is invalid or has been revoked. Create a new personal access token in the Linode Cloud Manager, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.linode.com": "Your Linode API token is missing the read scopes needed to sync this data. Grant the required read-only access in the Linode Cloud Manager, then reconnect.",
        }

    def get_schemas(
        self,
        config: LinodeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = LINODE_ENDPOINTS[endpoint]
            has_incremental = bool(endpoint_config.incremental_fields)
            return SourceSchema(
                name=endpoint,
                # Events are an immutable, append-only audit log — offer append (server-side cursor via
                # X-Filter) but never merge/upsert. Endpoints with no server-side filter are full refresh.
                supports_incremental=has_incremental and not endpoint_config.append_only,
                supports_append=has_incremental,
                incremental_fields=endpoint_config.incremental_fields,
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: LinodeSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_linode_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LinodeResumeConfig]:
        return ResumableSourceManager[LinodeResumeConfig](inputs, LinodeResumeConfig)

    def source_for_pipeline(
        self,
        config: LinodeSourceConfig,
        resumable_source_manager: ResumableSourceManager[LinodeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return linode_source(
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
