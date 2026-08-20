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

from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, Integration, OauthIntegration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.quickbooks import (
    QuickBooksSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.quickbooks.quickbooks import (
    QuickBooksResumeConfig,
    quickbooks_source,
    validate_credentials as validate_quickbooks_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.quickbooks.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Written onto the integration during the OAuth callback from Intuit's `realmId` param.
REALM_ID_CONFIG_KEY = "quickbooks_realm_id"

# `Integration.kind` this source will accept — shared by the OAuth field and the lookup below so
# the kind offered in the wizard and the kind enforced at sync time cannot drift apart.
INTEGRATION_KIND = "quickbooks"

_MISSING_REALM_ID_ERROR = "QuickBooks company ID is missing from this connection"
_TOKEN_REFRESH_FAILED_ERROR = "QuickBooks access token could not be refreshed"
_MISSING_ACCESS_TOKEN_ERROR = "QuickBooks access token not found"


@SourceRegistry.register
class QuickBooksSource(ResumableSource[QuickBooksSourceConfig, QuickBooksResumeConfig], OAuthMixin):
    # The Accounting API version lives in the request path (`/v3/company/{realmId}`).
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://developer.intuit.com/app/developer/qbo/docs/api/accounting/all-entities/account"

    lists_tables_without_credentials = True  # static entity catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.QUICKBOOKS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://quickbooks.api.intuit.com": "QuickBooks rejected the access token. Please reconnect your QuickBooks company.",
            "401 Client Error: Unauthorized for url: https://sandbox-quickbooks.api.intuit.com": "QuickBooks rejected the access token. Please reconnect your QuickBooks company.",
            "403 Client Error: Forbidden for url: https://quickbooks.api.intuit.com": "QuickBooks denied access to this company. Reconnect and grant access to the accounting data.",
            "403 Client Error: Forbidden for url: https://sandbox-quickbooks.api.intuit.com": "QuickBooks denied access to this company. Reconnect and grant access to the accounting data.",
            # Deterministic credential and config errors from the OAuth mixin and the helpers below.
            # The integration row is gone, unconfigured, or unrefreshable, so retrying can't help.
            # Matched as a substring, since the trailing integration ID varies.
            "Missing integration ID": "QuickBooks is not connected. Please connect your QuickBooks company.",
            "Integration not found": "The linked QuickBooks connection no longer exists. Please reconnect your QuickBooks company.",
            "QuickBooks app not configured": "The QuickBooks app is not configured on this PostHog instance. Please contact support.",
            _MISSING_REALM_ID_ERROR: "This QuickBooks connection is missing its company ID. Please reconnect your QuickBooks company.",
            _TOKEN_REFRESH_FAILED_ERROR: "QuickBooks could not refresh the connection. Please reconnect your QuickBooks company.",
            _MISSING_ACCESS_TOKEN_ERROR: "The QuickBooks connection has no access token. Please reconnect your QuickBooks company.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.QUICK_BOOKS,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            keywords=["qb", "qbo", "quickbooks online", "intuit"],
            label="QuickBooks",
            caption="""Connect your QuickBooks Online company to pull invoices, payments, customers, and the rest of your accounting data into the PostHog Data warehouse.

Click connect, sign in with Intuit, and choose the company you want to sync. PostHog asks for access to your accounting data (`com.intuit.quickbooks.accounting`) and picks up the company from the connection, so there is nothing to copy across. Connect once per company.

Pick Sandbox only if you are connecting an Intuit sandbox company.""",
            iconPath="/static/services/quickbooks.png",
            docsUrl="https://posthog.com/docs/cdp/sources/quickbooks",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="quickbooks_integration_id",
                        label="QuickBooks company",
                        required=True,
                        kind=INTEGRATION_KIND,
                        requiredScopes="com.intuit.quickbooks.accounting",
                    ),
                    # Intuit runs one app across production and sandbox, so the environment only
                    # selects the API host and stays a source setting rather than a second OAuth kind.
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="production",
                        options=[
                            SourceFieldSelectConfigOption(label="Production", value="production"),
                            SourceFieldSelectConfigOption(label="Sandbox", value="sandbox"),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.quickbooks.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: QuickBooksSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def _get_integration(self, config: QuickBooksSourceConfig, team_id: int) -> Integration:
        integration = self.get_oauth_integration(config.quickbooks_integration_id, team_id)
        # `get_oauth_integration` scopes by ID and team only, so a same-team integration of any
        # other kind would otherwise be accepted here and have its bearer token sent to Intuit.
        # Deliberately the same message as a missing row: from this source's point of view a
        # non-QuickBooks integration is not a connection it can use, and reusing the wording keeps
        # it mapped to the curated non-retryable error below.
        if integration.kind != INTEGRATION_KIND:
            raise ValueError(f"Integration not found: {config.quickbooks_integration_id}")
        return integration

    def _get_realm_id(self, integration: Integration) -> str:
        # Written during the OAuth callback; `integration_id` holds the same value and covers rows
        # whose config was trimmed.
        realm_id = integration.config.get(REALM_ID_CONFIG_KEY) or integration.integration_id
        if not realm_id:
            raise ValueError(_MISSING_REALM_ID_ERROR)
        return str(realm_id)

    def _get_access_token(self, integration: Integration, force_refresh: bool = False) -> str:
        """Return a usable access token, renewing the hour-long Intuit token when it's due."""
        oauth_integration = OauthIntegration(integration)
        if force_refresh or oauth_integration.access_token_expired():
            oauth_integration.refresh_access_token()
            if integration.errors == ERROR_TOKEN_REFRESH_FAILED:
                raise ValueError(_TOKEN_REFRESH_FAILED_ERROR)

        if not integration.access_token:
            raise ValueError(_MISSING_ACCESS_TOKEN_ERROR)
        return integration.access_token

    def _renew_access_token(self, config: QuickBooksSourceConfig, team_id: int) -> str:
        """Mint a fresh token after Intuit rejects one mid-sync, re-reading the integration first."""
        return self._get_access_token(self._get_integration(config, team_id), force_refresh=True)

    def validate_credentials(
        self,
        config: QuickBooksSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            integration = self._get_integration(config, team_id)
            realm_id = self._get_realm_id(integration)
            access_token = self._get_access_token(integration)
        except ValueError as e:
            # The mixin and the helpers raise developer-facing messages that can carry an
            # integration ID. Reuse the curated wording from get_non_retryable_errors so the wizard
            # shows the same text, falling back to the raw message when unmapped.
            raw = str(e)
            for pattern, friendly in self.get_non_retryable_errors().items():
                if friendly and pattern in raw:
                    return False, friendly
            return False, raw

        if validate_quickbooks_credentials(
            environment=config.environment,
            realm_id=realm_id,
            access_token=access_token,
            api_version=self.resolve_api_version(api_version),
        ):
            return True, None

        return False, "Your QuickBooks connection is invalid or expired. Please reconnect it."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[QuickBooksResumeConfig]:
        return ResumableSourceManager[QuickBooksResumeConfig](inputs, QuickBooksResumeConfig)

    def source_for_pipeline(
        self,
        config: QuickBooksSourceConfig,
        resumable_source_manager: ResumableSourceManager[QuickBooksResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        integration = self._get_integration(config, inputs.team_id)

        return quickbooks_source(
            environment=config.environment,
            realm_id=self._get_realm_id(integration),
            access_token=self._get_access_token(integration),
            # A sync can outlive the hour-long token, so hand the transport a way to renew it.
            refresh_access_token=lambda: self._renew_access_token(config, inputs.team_id),
            entity_name=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
