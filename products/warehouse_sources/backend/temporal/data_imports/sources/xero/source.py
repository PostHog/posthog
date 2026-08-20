from typing import Optional, cast

import requests

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
)

from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, OauthIntegration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccount,
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.xero import XeroSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.xero.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.xero.xero import (
    XeroAuthError,
    XeroClient,
    XeroResumeConfig,
    validate_credentials as validate_xero_credentials,
    xero_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Mirrors the scope the PostHog Xero app requests (see `oauth_config_for_kind` in
# posthog/models/integration/oauth.py) so the form can warn when a connection is missing one.
REQUIRED_SCOPES = (
    "offline_access accounting.transactions.read accounting.contacts.read "
    "accounting.settings.read accounting.journals.read"
)


@SourceRegistry.register
class XeroSource(ResumableSource[XeroSourceConfig, XeroResumeConfig], OAuthMixin):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("2.0",)
    default_version = "2.0"
    api_docs_url = "https://developer.xero.com/documentation/api/accounting/overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.XERO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.xero.com": "Xero rejected your access token. Reconnect your Xero account.",
            "403 Client Error: Forbidden for url: https://api.xero.com": "Your Xero connection is missing a scope for this table. Reconnect your Xero account and grant the read scopes.",
            "is not connected to this app": "That Xero organization is no longer shared with PostHog. Reconnect your Xero account, or pick another organization.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.xero.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: XeroSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def _access_token(self, integration_id: int, team_id: int) -> str:
        """A usable access token for the linked Xero integration.

        Xero access tokens live 30 minutes, so a stored one is often stale by the time the source
        form asks for organizations; refreshing here keeps the picker working between syncs.
        """
        integration = self.get_oauth_integration(integration_id, team_id)

        oauth = OauthIntegration(integration)
        if oauth.access_token_expired():
            oauth.refresh_access_token()

        if integration.errors == ERROR_TOKEN_REFRESH_FAILED or not integration.access_token:
            raise XeroAuthError("Could not refresh the Xero credentials. Please reconnect your Xero account.")

        return integration.access_token

    def get_oauth_accounts(
        self, integration_id: int, team_id: int, search: str | None = None
    ) -> list[IntegrationAccount]:
        # A Xero login shares a handful of organizations at most, so `search` is left to the endpoint.
        try:
            access_token = self._access_token(integration_id, team_id)
        except ValueError as e:
            raise IntegrationAccountListingError(
                "The linked Xero integration could not be found. Please reconnect your Xero account."
            ) from e
        except XeroAuthError as e:
            raise IntegrationAccountListingError(str(e)) from e
        except requests.RequestException as e:
            # `refresh_access_token` only records the failure when Xero answers with a parseable
            # body — a network error, or an HTML error page it then fails to `.json()`, escapes
            # instead. Transient either way, so don't let it 500.
            raise IntegrationAccountListingError(
                "Could not reach Xero to refresh this connection. Please try again in a few minutes."
            ) from e

        try:
            organisations = XeroClient(access_token=access_token).list_organisations()
        except requests.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            if status_code in (401, 403):
                raise IntegrationAccountListingError(
                    "Xero rejected this connection. Please reconnect your Xero account."
                ) from e
            if status_code == 429:
                raise IntegrationAccountListingError(
                    "Xero is rate limiting this connection. Please wait a moment and try again."
                ) from e
            if status_code is not None and status_code >= 500:
                raise IntegrationAccountListingError(
                    "Xero is having trouble responding right now. Please try again in a few minutes."
                ) from e
            # Any other status means we built a bad request, which the user cannot fix.
            raise
        except requests.RequestException as e:
            raise IntegrationAccountListingError(
                "Xero is having trouble responding right now. Please try again in a few minutes."
            ) from e

        return [
            IntegrationAccount(
                value=organisation["tenantId"],
                display_name=organisation.get("tenantName") or organisation["tenantId"],
            )
            for organisation in organisations
        ]

    def validate_credentials(
        self,
        config: XeroSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.xero_integration_id or not config.tenant_id:
            return False, "A Xero account and an organization are required"

        try:
            access_token = self._access_token(config.xero_integration_id, team_id)
        except (ValueError, XeroAuthError) as e:
            return False, str(e)
        except requests.RequestException:
            return False, "Could not reach Xero to refresh this connection. Please try again in a few minutes."

        return validate_xero_credentials(access_token=access_token, tenant_id=config.tenant_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[XeroResumeConfig]:
        return ResumableSourceManager[XeroResumeConfig](inputs, XeroResumeConfig)

    def source_for_pipeline(
        self,
        config: XeroSourceConfig,
        resumable_source_manager: ResumableSourceManager[XeroResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        integration = self.get_oauth_integration(config.xero_integration_id, inputs.team_id)

        if not integration.access_token:
            raise ValueError(f"Xero access token not found for job {inputs.job_id}")

        return xero_source(
            access_token=integration.access_token,
            tenant_id=config.tenant_id,
            endpoint_name=inputs.schema_name,
            resumable_source_manager=resumable_source_manager,
            logger=inputs.logger,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.XERO,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Xero",
            caption="""Sync your Xero accounting data into the PostHog Data warehouse.

Connect your Xero account, then choose the organization you want to sync. PostHog asks for read access to transactions, contacts, settings and journals.""",
            iconPath="/static/services/xero.png",
            docsUrl="https://posthog.com/docs/cdp/sources/xero",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="xero_integration_id",
                        label="Xero account",
                        required=True,
                        kind="xero",
                        requiredScopes=REQUIRED_SCOPES,
                    ),
                    SourceFieldOauthAccountSelectConfig(
                        name="tenant_id",
                        label="Organization",
                        integrationField="xero_integration_id",
                        integrationKind="xero",
                        required=True,
                        placeholder="Select a Xero organization",
                    ),
                ],
            ),
        )
