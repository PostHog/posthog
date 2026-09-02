from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.app_store_connect import (
    APP_STORE_CONNECT_ANALYTICS_CREATE_FORBIDDEN_ERROR,
    APP_STORE_CONNECT_ANALYTICS_INACTIVE_ERROR,
    APP_STORE_CONNECT_MISSING_VENDOR_NUMBER_ERROR,
    APP_STORE_CONNECT_READ_FORBIDDEN_ERROR,
    AppStoreConnectResumeConfig,
    app_store_connect_source,
    check_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.settings import (
    APP_STORE_CONNECT_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    REPORT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appstoreconnect import (
    AppStoreConnectSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_MISSING_VENDOR_NUMBER = (
    "Add your vendor number in the source settings to sync sales and subscription reports. "
    "You can find it in App Store Connect under Payments and Financial Reports."
)


@SourceRegistry.register
class AppStoreConnectSource(ResumableSource[AppStoreConnectSourceConfig, AppStoreConnectResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://developer.apple.com/documentation/appstoreconnectapi"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APPSTORECONNECT

    @property
    def get_source_config(self) -> SourceConfig:
        from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.restatements import (
            restatement_caption,
        )

        caption = """Pull your App Store apps, versions, builds, reviews and sales reports into the PostHog Data warehouse.

An Account Holder or Admin creates an API key under **Users and Access → Integrations → App Store Connect API** in App Store Connect. Copy the issuer ID and key ID from that page, then paste the contents of the `.p8` private key file you download. Apple only lets you download that file once, so keep a copy.

Sales and subscription reports also need your vendor number (App Store Connect → **Payments and Financial Reports**) and a key with the Finance, Sales, or Admin role. Leave it blank if you only want app, review and build data.

The analytics tables need a key with the Admin role. Apple lets only an Admin key start an analytics report."""
        restatement_note = restatement_caption()
        if restatement_note:
            caption = f"{caption}\n\n{restatement_note}"

        return SourceConfig(
            name=SchemaExternalDataSourceType.APP_STORE_CONNECT,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Apple (App Store Connect)",
            releaseStatus=ReleaseStatus.BETA,
            keywords=["app store", "ios", "apple", "mobile analytics"],
            caption=caption,
            iconPath="/static/services/app_store_connect.png",
            docsUrl="https://posthog.com/docs/cdp/sources/app-store-connect",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="issuer_id",
                        label="Issuer ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="57246542-96fe-1a63-e053-0824d011072a",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="key_id",
                        label="Key ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="2X9R4HXF34",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="private_key",
                        label="Private key (.p8 contents)",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="-----BEGIN PRIVATE KEY-----",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="vendor_number",
                        label="Vendor number (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="85234567",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )
        from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.restatements import (
            with_restatement_guidance,
        )

        # Applied at read time so every analytics stream in the catalog carries its restatement
        # dedup query, wherever in the module its entry was added.
        return with_restatement_guidance(CANONICAL_DESCRIPTIONS)

    def get_canonical_descriptions_for_table_prefix(self, table_prefix: str) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )
        from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.restatements import (
            with_restatement_guidance,
        )

        # The dedup queries name a physical table, so they are rebuilt for this source's prefix.
        return with_restatement_guidance(CANONICAL_DESCRIPTIONS, table_prefix=table_prefix)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Match the stable status text plus the base host, not the per-request path and cursor.
        return {
            "401 Client Error: Unauthorized for url: https://api.appstoreconnect.apple.com": "App Store Connect rejected your API key. Check the issuer ID, key ID and private key, or generate a new key, then reconnect.",
            # A 403 on the analytics report request create. Apple gates it on Admin, not the read
            # roles. Kept before the read message so the create case never inherits the read wording.
            APP_STORE_CONNECT_ANALYTICS_CREATE_FORBIDDEN_ERROR: APP_STORE_CONNECT_ANALYTICS_CREATE_FORBIDDEN_ERROR,
            # A 403 on the create where the app's ongoing request had stopped for inactivity.
            APP_STORE_CONNECT_ANALYTICS_INACTIVE_ERROR: APP_STORE_CONNECT_ANALYTICS_INACTIVE_ERROR,
            # A 403 on a read. The key's role genuinely can't read this table.
            APP_STORE_CONNECT_READ_FORBIDDEN_ERROR: APP_STORE_CONNECT_READ_FORBIDDEN_ERROR,
            # Any 403 that didn't come through the custom raises still fails fast with the read message.
            "403 Client Error: Forbidden for url: https://api.appstoreconnect.apple.com": APP_STORE_CONNECT_READ_FORBIDDEN_ERROR,
            # A report sync selected without a vendor number can never read `/v1/salesReports`, so fail
            # fast instead of retrying the activity's whole budget until the user adds the number.
            APP_STORE_CONNECT_MISSING_VENDOR_NUMBER_ERROR: APP_STORE_CONNECT_MISSING_VENDOR_NUMBER_ERROR,
        }

    def get_retryable_errors(self) -> set[str]:
        # `_get` has no retry loop of its own — it relies on the tracked session's urllib3 adapter
        # to retry a connection failure, read timeout, or 429/5xx response. Once that budget is
        # exhausted, Temporal retries the whole activity, so this is transient and self-recovering.
        # The host is fixed (never user input), so matching on it doesn't risk swallowing an
        # unrelated failure. `requests.Response.raise_for_status` derives "Server Error"/"Client
        # Error" prefixes from the status code alone, not the vendor's reason text, so they're
        # stable to match on (see mailchimp/convex sources for the same pattern).
        return {
            "HTTPSConnectionPool(host='api.appstoreconnect.apple.com'",
            "Server Error",
            "429 Client Error",
        }

    def get_schemas(
        self,
        config: AppStoreConnectSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            should_sync_default={
                name: endpoint.should_sync_default for name, endpoint in APP_STORE_CONNECT_ENDPOINTS.items()
            },
        )
        for schema in schemas:
            schema.detected_primary_keys = APP_STORE_CONNECT_ENDPOINTS[schema.name].primary_keys
        return schemas

    def get_endpoint_permissions(
        self,
        config: AppStoreConnectSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        # The report endpoints can't be read at all without a vendor number, so flag them in the picker
        # instead of letting the user select a table that will fail at sync time.
        if config.vendor_number:
            return dict.fromkeys(endpoints)
        return {name: (_MISSING_VENDOR_NUMBER if name in REPORT_ENDPOINTS else None) for name in endpoints}

    def validate_credentials(
        self,
        config: AppStoreConnectSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name in REPORT_ENDPOINTS and not config.vendor_number:
            return False, _MISSING_VENDOR_NUMBER

        status, message = check_credentials(config.issuer_id, config.key_id, config.private_key)

        if status is None:
            return False, message or "Could not reach App Store Connect. Please try again."
        if status == 401:
            return False, "App Store Connect rejected your API key. Check the issuer ID, key ID and private key."
        if status == 403 and schema_name is None:
            # A valid key whose role can't read `/v1/apps` is still a real key — the per-table check
            # reports what it can't reach, so don't block source creation on it.
            return True, None
        if status == 403:
            return False, "Your App Store Connect API key does not have permission to read this data."
        if status == 200:
            return True, None
        return False, f"App Store Connect returned status {status}"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AppStoreConnectResumeConfig]:
        return ResumableSourceManager[AppStoreConnectResumeConfig](inputs, AppStoreConnectResumeConfig)

    def source_for_pipeline(
        self,
        config: AppStoreConnectSourceConfig,
        resumable_source_manager: ResumableSourceManager[AppStoreConnectResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return app_store_connect_source(
            issuer_id=config.issuer_id,
            key_id=config.key_id,
            private_key=config.private_key,
            vendor_number=config.vendor_number,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
