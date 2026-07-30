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
from products.warehouse_sources.backend.temporal.data_imports.sources.fleetio.fleetio import (
    FleetioResumeConfig,
    fleetio_source,
    validate_credentials as validate_fleetio_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fleetio.settings import (
    ENDPOINTS,
    FLEETIO_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FleetioSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FleetioSource(ResumableSource[FleetioSourceConfig, FleetioResumeConfig]):
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://developer.fleetio.com"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FLEETIO

    @property
    def connection_host_fields(self) -> list[str]:
        # `account_token` selects which Fleetio account the stored API key is sent to. Editing it on
        # an existing source must force the key to be re-entered — otherwise an editor could retarget
        # the preserved key at another Fleetio account, exposing it across a tenant boundary the user
        # never approved.
        return ["account_token"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FLEETIO,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Fleetio",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Fleetio API key and account token to pull your Fleetio fleet data into the PostHog Data warehouse.

Create an API key under **Account Menu → Account Settings → API Keys** in Fleetio. Your account token is shown on the same page (it identifies your Fleetio account).""",
            iconPath="/static/services/fleetio.png",
            docsUrl="https://posthog.com/docs/cdp/sources/fleetio",
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
                        name="account_token",
                        label="Account token",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.fleetio.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
            # Retrying can never satisfy a credential problem. Match the stable status text and base
            # host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://secure.fleetio.com": "Your Fleetio API key or account token is invalid or has been revoked. Generate a new API key in your Fleetio account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://secure.fleetio.com": "Your Fleetio API key does not have permission to read this data. Check the key's permissions in your Fleetio account settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: FleetioSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = FLEETIO_ENDPOINTS[endpoint]
            has_incremental = len(endpoint_config.incremental_fields) > 0
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: FleetioSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_fleetio_credentials(config.api_key, config.account_token):
            return True, None

        return False, "Invalid Fleetio API key or account token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FleetioResumeConfig]:
        return ResumableSourceManager[FleetioResumeConfig](inputs, FleetioResumeConfig)

    def source_for_pipeline(
        self,
        config: FleetioSourceConfig,
        resumable_source_manager: ResumableSourceManager[FleetioResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return fleetio_source(
            api_key=config.api_key,
            account_token=config.account_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
