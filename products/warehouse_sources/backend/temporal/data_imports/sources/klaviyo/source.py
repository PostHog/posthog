from datetime import date
from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    FieldType,
    ResumableSource,
    VersionDeprecation,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.klaviyo import (
    KlaviyoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.klaviyo.constants import (
    KLAVIYO_API_VERSION_2024_10_15,
    KLAVIYO_API_VERSION_2026_07_15,
)
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
    supported_versions = (KLAVIYO_API_VERSION_2024_10_15, KLAVIYO_API_VERSION_2026_07_15)
    default_version = KLAVIYO_API_VERSION_2026_07_15
    api_docs_url = "https://developers.klaviyo.com"
    # Klaviyo retires a revision two years after release, falling forward / returning 410 thereafter.
    deprecated_versions = (VersionDeprecation(version=KLAVIYO_API_VERSION_2024_10_15, sunset_at=date(2026, 10, 15)),)

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

Grant read permissions for the data you want to sync. Tables you have not granted access to are skipped:
- Accounts
- Campaigns
- Catalogs
- Coupon codes
- Coupons
- Custom objects
- Events
- Flows
- Forms
- Images
- Lists
- Metrics
- Profiles
- Push tokens
- Reviews
- Segments
- Tags
- Templates
- Web feeds
- Webhooks (requires Klaviyo's Advanced KDP add-on)

The campaign and flow performance tables need a conversion metric. Leave the conversion metric ID blank to use your Placed Order metric, or paste the ID of another metric from [your Klaviyo metrics](https://www.klaviyo.com/analytics/metrics).
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
                    SourceFieldInputConfig(
                        name="conversion_metric_id",
                        label="Conversion metric ID (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="RESQ6t",
                        secret=False,
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
        # Ordered most-specific first: the first matching entry supplies the user-facing message
        # (see `update_external_data_job_model`), so plan gating must precede the blanket 403 entry.
        return {
            # Klaviyo gates some endpoints (webhooks today) behind its paid Advanced KDP add-on and
            # 403s with this body detail even when the key's read scope is granted. `_fetch_page`
            # appends the detail to the HTTPError message so it's matchable here; without this entry
            # the blanket 403 mapping below blames the key's scopes, which the user can never fix.
            "You must have Advanced KDP enabled": "Your Klaviyo plan does not include API access to this table. Klaviyo limits this endpoint to accounts with the Advanced KDP add-on, even when the API key has the required read scope. Syncing is paused for this table; re-enable it if you add Advanced KDP to your Klaviyo account.",
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
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Events are immutable - append-only is the only sync mode
        append_only_endpoints = {"events"}
        # An endpoint's incremental lookback intentionally re-pulls a window of rows each run; only
        # merge dedupes those on the primary key, append would materialize them as duplicates.
        merge_only_endpoints = {
            name for name, endpoint_config in KLAVIYO_ENDPOINTS.items() if endpoint_config.incremental_lookback
        }

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = KLAVIYO_ENDPOINTS[endpoint]
            has_incremental = INCREMENTAL_FIELDS.get(endpoint, None) is not None
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental and endpoint not in append_only_endpoints,
                supports_append=has_incremental and endpoint not in merge_only_endpoints,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=endpoint_config.description,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: KlaviyoSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_klaviyo_credentials(config.api_key, self.resolve_api_version(api_version)):
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
            api_version=self.resolve_api_version(inputs.api_version),
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
            conversion_metric_id=config.conversion_metric_id,
        )
