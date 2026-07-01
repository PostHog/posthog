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
from products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.bluetally import (
    BluetallyResumeConfig,
    bluetally_source,
    validate_credentials as validate_bluetally_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.settings import (
    BLUETALLY_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BluetallySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BluetallySource(ResumableSource[BluetallySourceConfig, BluetallyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BLUETALLY

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored API key is sent with whatever `tenant_id` is configured, so changing it
        # retargets the saved credential at a different tenant — force secret re-entry on a change.
        return ["tenant_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BLUETALLY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="BlueTally",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your BlueTally API key to sync your IT asset management data into the PostHog Data warehouse.

Create an API key in BlueTally under **Settings → API Keys**, then paste it here.

If your account has multi-tenancy enabled, also enter the tenant ID the key should act on.""",
            iconPath="/static/services/bluetally.png",
            docsUrl="https://posthog.com/docs/cdp/sources/bluetally",
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
                    SourceFieldInputConfig(
                        name="tenant_id",
                        label="Tenant ID (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or expired API key surfaces as a requests HTTPError when `_fetch_page`
            # calls `raise_for_status()`. Retrying can never satisfy a credential problem, so stop
            # the sync. Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://app.bluetallyapp.com": "Your BlueTally API key is invalid or has expired. Create a new key under Settings → API Keys in BlueTally, then reconnect.",
            "403 Client Error: Forbidden for url: https://app.bluetallyapp.com": "Your BlueTally API key does not have permission to read this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: BluetallySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # BlueTally exposes no server-side timestamp filter (only exact-match filters and sort), so
        # every endpoint is full refresh — incremental would re-fetch every page each sync anyway.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                detected_primary_keys=BLUETALLY_ENDPOINTS[endpoint].primary_keys,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: BluetallySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        path = BLUETALLY_ENDPOINTS[schema_name].path if schema_name in BLUETALLY_ENDPOINTS else "/assets"
        if validate_bluetally_credentials(config.api_key, config.tenant_id, path):
            return True, None

        return False, "Invalid BlueTally API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BluetallyResumeConfig]:
        return ResumableSourceManager[BluetallyResumeConfig](inputs, BluetallyResumeConfig)

    def source_for_pipeline(
        self,
        config: BluetallySourceConfig,
        resumable_source_manager: ResumableSourceManager[BluetallyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return bluetally_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            tenant_id=config.tenant_id,
        )
