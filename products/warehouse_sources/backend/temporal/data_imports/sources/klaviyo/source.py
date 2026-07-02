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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import KlaviyoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.klaviyo.klaviyo import (
    KlaviyoResumeConfig,
    klaviyo_source,
    validate_credentials as validate_klaviyo_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.klaviyo.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    KLAVIYO_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KlaviyoSource(ResumableSource[KlaviyoSourceConfig, KlaviyoResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KLAVIYO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KLAVIYO,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Klaviyo",
            releaseStatus=ReleaseStatus.GA,
            caption="""Enter your Klaviyo API key to automatically pull your Klaviyo data into the PostHog Data warehouse.

You can create a private API key in your [Klaviyo account settings](https://www.klaviyo.com/settings/account/api-keys).

Make sure to grant the following read permissions:
- Accounts
- Campaigns
- Events
- Flows
- Lists
- Metrics
- Profiles
""",
            iconPath="/static/services/klaviyo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/klaviyo",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="pk_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.klaviyo.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid, revoked, or insufficiently-scoped Klaviyo API key surfaces as a requests
            # HTTPError when `fetch_page` calls `raise_for_status()`. Retrying can never satisfy a
            # credential problem, so stop the sync. Match the stable status text and base host, not
            # the per-request path/query/timestamp.
            "401 Client Error: Unauthorized for url: https://a.klaviyo.com": "Your Klaviyo API key is invalid or has been revoked. Create a new private API key in your Klaviyo account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://a.klaviyo.com": "Your Klaviyo API key is missing the read permissions needed to sync this data. Grant the required read scopes in your Klaviyo account settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: KlaviyoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Events are immutable - append-only is the only sync mode
        append_only_endpoints = {"events"}

        def _description(endpoint: str) -> str | None:
            if endpoint == "events":
                return "Only syncs the last 365 days on initial sync"
            if KLAVIYO_ENDPOINTS[endpoint].fan_out_over_lists:
                return "Maps which profiles belong to which list as {list_id, profile_id} rows. Full refresh only"
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = KLAVIYO_ENDPOINTS[endpoint]
            # Fan-out endpoints have no server-side incremental filter, so they're full refresh only.
            has_incremental = (
                INCREMENTAL_FIELDS.get(endpoint, None) is not None and not endpoint_config.fan_out_over_lists
            )
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental and endpoint not in append_only_endpoints,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: KlaviyoSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_klaviyo_credentials(config.api_key):
            return True, None

        return False, "Invalid Klaviyo API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[KlaviyoResumeConfig]:
        return ResumableSourceManager[KlaviyoResumeConfig](inputs, KlaviyoResumeConfig)

    def source_for_pipeline(
        self,
        config: KlaviyoSourceConfig,
        resumable_source_manager: ResumableSourceManager[KlaviyoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return klaviyo_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
