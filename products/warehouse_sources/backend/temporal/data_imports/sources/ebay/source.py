import functools
from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.ebay.ebay import (
    EbayResumeConfig,
    check_endpoint_permissions as check_ebay_endpoint_permissions,
    ebay_source,
    validate_credentials as validate_ebay_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ebay.oauth import resolve_ebay_oauth_token
from products.warehouse_sources.backend.temporal.data_imports.sources.ebay.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ebay import EbaySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Every scope the source calls, in the space-separated form eBay's `scope` parameter uses. The
# frontend diffs it against what the seller actually granted and offers a reconnect when it falls
# short. `commerce.identity.readonly` is what names the connected account.
REQUIRED_SCOPES = " ".join(
    [
        "https://api.ebay.com/oauth/api_scope",
        "https://api.ebay.com/oauth/api_scope/commerce.identity.readonly",
        "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
        "https://api.ebay.com/oauth/api_scope/sell.finances",
        "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
    ]
)

MARKETPLACES: list[tuple[str, str]] = [
    ("EBAY_US", "United States"),
    ("EBAY_GB", "United Kingdom"),
    ("EBAY_DE", "Germany"),
    ("EBAY_AU", "Australia"),
    ("EBAY_CA", "Canada"),
    ("EBAY_FR", "France"),
    ("EBAY_IT", "Italy"),
    ("EBAY_ES", "Spain"),
    ("EBAY_NL", "Netherlands"),
    ("EBAY_BE", "Belgium"),
    ("EBAY_IE", "Ireland"),
    ("EBAY_AT", "Austria"),
    ("EBAY_CH", "Switzerland"),
    ("EBAY_PL", "Poland"),
    ("EBAY_HK", "Hong Kong"),
    ("EBAY_SG", "Singapore"),
    ("EBAY_MOTORS", "eBay Motors"),
]


@SourceRegistry.register
class EbaySource(ResumableSource[EbaySourceConfig, EbayResumeConfig], OAuthMixin):
    api_docs_url = "https://developer.ebay.com/api-docs/static/ebay-rest-landing.html"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EBAY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.EBAY,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="eBay",
            caption="""Pull your eBay seller data into the PostHog Data warehouse: orders, monetary transactions, payouts and inventory.

Connect the eBay account that does the selling, then pick the marketplace it sells on. eBay will ask you to let PostHog view:

- your order fulfillments
- your payments and payouts
- your inventory and offers
- your basic account information, which is used to name the connection

eBay expires the connection after 18 months, and revokes it when the seller changes their password. Reconnect here if syncs start failing.""",
            iconPath="/static/services/ebay.png",
            docsUrl="https://posthog.com/docs/cdp/sources/ebay",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["marketplace", "ebay seller"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="ebay_integration_id",
                        label="eBay account",
                        required=True,
                        kind="ebay",
                        requiredScopes=REQUIRED_SCOPES,
                    ),
                    SourceFieldSelectConfig(
                        name="marketplace_id",
                        label="Marketplace",
                        required=True,
                        defaultValue="EBAY_US",
                        options=[
                            SourceFieldSelectConfigOption(label=label, value=value) for value, label in MARKETPLACES
                        ],
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.ebay.com": (
                "Your eBay connection is no longer valid. Reconnect your eBay account and try again."
            ),
            "403 Client Error: Forbidden for url: https://api.ebay.com": (
                "Your eBay connection is missing the permission needed for this data. Reconnect your eBay account "
                "and allow access to your order fulfillments, payments and payouts, and inventory."
            ),
            # Deterministic credential errors from OAuthMixin and the token resolver: the integration
            # row is gone or unusable, so a retry can never succeed. Matched on the stable prefix so
            # the volatile integration ID is ignored.
            "Missing integration ID": "Your eBay account is not connected. Reconnect it and try again.",
            "Integration not found": "The linked eBay connection no longer exists. Reconnect your eBay account.",
            "eBay access token not found": "Your eBay connection has no access token. Reconnect your eBay account.",
        }

    def get_retryable_errors(self) -> set[str]:
        # The tracked transport already backs off on eBay's per-app call limit before giving
        # up, so a surfaced 429 is transient rather than a failure worth alerting on.
        return {"429 Client Error"}

    def _access_token(self, config: EbaySourceConfig, team_id: int) -> str:
        """Current access token for the connected eBay account, refreshed if it has expired."""
        integration_id = config.ebay_integration_id
        # Ownership check first: a missing or foreign integration is a stable ValueError rather
        # than the DoesNotExist the token resolver would raise, which retries would never fix.
        self.get_oauth_integration(integration_id, team_id)
        return resolve_ebay_oauth_token(integration_id, team_id)

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.ebay.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: EbaySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=len(INCREMENTAL_FIELDS[endpoint]) > 0,
                supports_append=len(INCREMENTAL_FIELDS[endpoint]) > 0,
                incremental_fields=INCREMENTAL_FIELDS[endpoint],
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: EbaySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            access_token = self._access_token(config, team_id)
        except ValueError:
            return False, "Connect an eBay account to continue"

        is_valid, is_forbidden = validate_ebay_credentials(
            access_token=access_token,
            marketplace_id=config.marketplace_id,
            schema_name=schema_name,
        )
        if is_valid:
            return True, None

        # A 403 means the connection is genuine but that permission wasn't granted. Sellers
        # commonly authorize only the APIs they want, so accept it at source-create and reject
        # it only when validating a specific table.
        if is_forbidden and schema_name is None:
            return True, None

        if is_forbidden:
            return False, f"Your eBay connection is missing the permission required to sync '{schema_name}'"

        return False, "Your eBay connection is invalid or expired. Reconnect it and try again."

    def get_endpoint_permissions(
        self, config: EbaySourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        try:
            access_token = self._access_token(config, team_id)
        except ValueError:
            # Never block the schema picker on a credential problem; validate_credentials reports it.
            return dict.fromkeys(endpoints)

        return check_ebay_endpoint_permissions(
            access_token=access_token,
            marketplace_id=config.marketplace_id,
            endpoints=endpoints,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[EbayResumeConfig]:
        # Endpoints store incompatible cursors (filter window + offset vs parent offset),
        # so each keeps its resume state in its own slot.
        return ResumableSourceManager[EbayResumeConfig](inputs, EbayResumeConfig).with_namespace(inputs.schema_name)

    def source_for_pipeline(
        self,
        config: EbaySourceConfig,
        resumable_source_manager: ResumableSourceManager[EbayResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        integration_id = config.ebay_integration_id
        return ebay_source(
            access_token=self._access_token(config, inputs.team_id),
            marketplace_id=config.marketplace_id,
            # eBay access tokens last two hours, so a long backfill re-mints mid-sync.
            token_refresher=functools.partial(resolve_ebay_oauth_token, integration_id, inputs.team_id),
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
