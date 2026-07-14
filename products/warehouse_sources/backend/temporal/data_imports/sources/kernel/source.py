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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import KernelSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kernel.kernel import (
    kernel_source,
    validate_credentials as validate_kernel_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kernel.settings import ENDPOINTS, KERNEL_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KernelSource(SimpleSource[KernelSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog - safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KERNEL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KERNEL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Kernel",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Kernel API key to sync your Kernel browser-infrastructure data into the PostHog Data warehouse.

You can create an API key in your [Kernel dashboard](https://dashboard.onkernel.com) under API keys. Kernel keys are long-lived and grant organization-wide read access.""",
            iconPath="/static/services/kernel.png",
            docsUrl="https://posthog.com/docs/cdp/sources/kernel",
            keywords=["browser", "automation", "agents", "infrastructure"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.kernel.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.onkernel.com": "Your Kernel API key is invalid or has been revoked. Create a new key in your Kernel dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.onkernel.com": "Your Kernel API key does not have access to this data. Check the key's permissions in your Kernel dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: KernelSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = KERNEL_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                # Full refresh only - Kernel's server-side time filters are unverified for this
                # alpha release, so no incremental/append sync mode is offered yet.
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                should_sync_default=endpoint_config.should_sync_default,
                description=endpoint_config.description,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: KernelSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        ok, status = validate_kernel_credentials(config.api_key)
        if ok:
            return True, None

        # A valid token that lacks scope for one endpoint must not block source creation - the user
        # may only intend to sync the tables they can reach. Only reject 403 when probing a specific
        # schema; sync-time 403s are handled by get_non_retryable_errors().
        if status == 403 and schema_name is None:
            return True, None

        return False, "Invalid Kernel API key"

    def source_for_pipeline(self, config: KernelSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return kernel_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
