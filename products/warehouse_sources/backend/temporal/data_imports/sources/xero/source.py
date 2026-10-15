from typing import Optional, cast

import requests

from posthog.models.integration import Integration

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
)
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.xero import XeroSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.xero.oauth import (
    XeroIntegrationAuth,
    resolve_xero_oauth_token,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.xero.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.xero.xero import (
    XeroResumeConfig,
    list_organisations,
    probe_organisation,
    xero_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_RECONNECT_MESSAGE = "Xero rejected the connection. Reconnect your Xero account, then try again."


@SourceRegistry.register
class XeroSource(OAuthMixin, ResumableSource[XeroSourceConfig, XeroResumeConfig]):
    codebase_detection = detect(
        env=("^XERO_",),
        npm=("xero-node",),
        pypi=("xero-python",),
        composer=("xeroapi/xero-php-oauth2",),
        rubygems=("xero-ruby",),
        maven=("com.github.xeroapi:xero-java",),
    )
    setup_requires_ui = True

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://developer.xero.com/documentation/api/accounting/overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.XERO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.XERO,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Xero",
            keywords=["accounting", "invoices"],
            caption="Sync invoices, contacts, payments, bank transactions and the chart of accounts from one Xero organisation into the PostHog Data warehouse.",
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
                    ),
                    SourceFieldOauthAccountSelectConfig(
                        name="tenant_id",
                        label="Organisation",
                        integrationField="xero_integration_id",
                        integrationKind="xero",
                        caption="Each source syncs one organisation. Add another Xero source for each extra organisation.",
                        required=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.xero.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.xero.com": _RECONNECT_MESSAGE,
            "403 Client Error: Forbidden for url: https://api.xero.com": "Xero refused access to this organisation or table. Check that the connected Xero user can still open the organisation, then reconnect.",
            "Integration not found": "The linked Xero connection no longer exists. Reconnect your Xero account.",
            "Xero app not configured": "Xero is not configured on this PostHog instance. Contact support.",
        }

    def get_schemas(
        self,
        config: XeroSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=tuple(INCREMENTAL_FIELDS))

    def _access_token(self, integration_id: int, team_id: int) -> str:
        integration = self.get_oauth_integration(integration_id, team_id)
        # The lookup only scopes to the team, so reject another provider's integration before sending its token.
        if integration.kind != Integration.IntegrationKind.XERO:
            raise ValueError(f"Integration not found: {integration_id}")
        return resolve_xero_oauth_token(integration_id, team_id)

    def _build_auth(self, config: XeroSourceConfig, team_id: int) -> AuthConfigBase:
        token = self._access_token(config.xero_integration_id, team_id)
        return XeroIntegrationAuth(config.xero_integration_id, team_id, token)

    def get_oauth_accounts(
        self, integration_id: int, team_id: int, search: str | None = None
    ) -> list[IntegrationAccount]:
        try:
            organisations = list_organisations(self._access_token(integration_id, team_id))
        except ValueError:
            raise IntegrationAccountListingError("The Xero connection no longer exists. Reconnect your Xero account.")
        except requests.HTTPError:
            raise IntegrationAccountListingError(_RECONNECT_MESSAGE)
        if not organisations:
            raise IntegrationAccountListingError(
                "This Xero user has no organisation connected to PostHog. Reconnect and select an organisation in Xero."
            )
        return [
            IntegrationAccount(value=organisation["tenantId"], display_name=organisation["tenantName"])
            for organisation in organisations
        ]

    def validate_credentials(
        self,
        config: XeroSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            token = self._access_token(config.xero_integration_id, team_id)
        except ValueError:
            return False, "The Xero connection no longer exists. Reconnect your Xero account."
        status = probe_organisation(token, config.tenant_id)
        if status == 200:
            return True, None
        if status in (401, 403):
            return False, "Xero refused access to this organisation. Pick an organisation the connected user can open."
        return False, "Could not reach Xero. Try again in a few minutes."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[XeroResumeConfig]:
        return ResumableSourceManager[XeroResumeConfig](inputs, XeroResumeConfig)

    def source_for_pipeline(
        self,
        config: XeroSourceConfig,
        resumable_source_manager: ResumableSourceManager[XeroResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return xero_source(
            auth=self._build_auth(config, inputs.team_id),
            tenant_id=config.tenant_id,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )
