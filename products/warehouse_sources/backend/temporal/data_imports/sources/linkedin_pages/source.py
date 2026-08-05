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

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, Integration, OauthIntegration

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.linkedinpages import (
    LinkedinPagesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_pages.linkedin_pages import (
    LINKEDIN_API_VERSION,
    LinkedinPagesApiError,
    LinkedinPagesClient,
    LinkedinPagesDailyRateLimitError,
    LinkedinPagesResumeConfig,
    LinkedinPagesRetryableError,
    linkedin_pages_source,
    probe_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_pages.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Page, follower and share statistics plus the organizationAcls lookup all sit behind
# rw_organization_admin; the posts finder needs r_organization_social.
REQUIRED_SCOPES = "rw_organization_admin r_organization_social"

INTEGRATION_KIND = "linkedin-pages"


@SourceRegistry.register
class LinkedinPagesSource(ResumableSource[LinkedinPagesSourceConfig, LinkedinPagesResumeConfig], OAuthMixin):
    api_docs_url = "https://learn.microsoft.com/en-us/linkedin/marketing/community-management/organizations/organization-lookup-api"

    supported_versions = (LINKEDIN_API_VERSION,)
    default_version = LINKEDIN_API_VERSION

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LINKEDINPAGES

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LINKEDIN_PAGES,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            keywords=["linkedin company pages", "linkedin organization"],
            label="LinkedIn Pages",
            caption="""Pull your LinkedIn company page statistics, follower growth and posts into the PostHog Data warehouse.

Connect a LinkedIn account that administers the pages you want to sync. LinkedIn will ask you to grant PostHog access to manage your pages and read their reporting data, and to read your pages' posts. Then pick the pages to sync, or leave the list empty to sync every page that account administers.""",
            iconPath="/static/services/linkedin_pages.png",
            docsUrl="https://posthog.com/docs/cdp/sources/linkedin-pages",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="linkedin_pages_integration_id",
                        label="LinkedIn account",
                        required=True,
                        kind=INTEGRATION_KIND,
                        requiredScopes=REQUIRED_SCOPES,
                    ),
                    SourceFieldOauthAccountSelectConfig(
                        name="organization_ids",
                        label="LinkedIn pages",
                        integrationField="linkedin_pages_integration_id",
                        integrationKind=INTEGRATION_KIND,
                        required=False,
                        multiple=True,
                        placeholder="Leave empty to sync every page you administer",
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_pages.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "LinkedIn API error (401)": "LinkedIn rejected the connected account. Reconnect your LinkedIn account.",
            "LinkedIn API error (403)": "LinkedIn denied access. The connected account must administer the page, and PostHog needs the page admin and page posts permissions. Reconnect and grant both.",
            # Stable LinkedIn error codes — none of these can be recovered by retrying.
            "REVOKED_ACCESS_TOKEN": "The LinkedIn access was revoked. Reconnect your LinkedIn account.",
            "RESTRICTED_MEMBER": "LinkedIn has restricted the connected account, so PostHog can no longer read your page data. Resolve the restriction with LinkedIn, then reconnect.",
            "RESOURCE_NOT_FOUND": "LinkedIn could not find the requested page. Check the selected pages, or clear the selection to sync every page the connected account administers.",
        }

    def get_linkedin_integration(self, integration_id: int, team_id: int) -> Integration:
        """The integration behind `linkedin_pages_integration_id`, pinned to the LinkedIn kind.

        `get_oauth_integration` filters on id and team only, so any of the team's integrations
        would otherwise resolve here and have its bearer token sent to LinkedIn. The id is
        client-supplied, so the kind is checked on every path that reads the token.
        """
        integration = self.get_oauth_integration(integration_id, team_id)
        if integration.kind != INTEGRATION_KIND:
            raise ValueError(f"Integration not found: {integration_id}")
        return integration

    def get_oauth_accounts(
        self, integration_id: int, team_id: int, search: str | None = None
    ) -> list[IntegrationAccount]:
        # A member administers few pages, so `search` is left to the endpoint's generic filter.
        try:
            integration = self.get_linkedin_integration(integration_id, team_id)
        except ValueError as e:
            raise IntegrationAccountListingError(
                "The linked LinkedIn integration could not be found. Please reconnect your LinkedIn account."
            ) from e

        oauth = OauthIntegration(integration)
        if oauth.access_token_expired():
            try:
                oauth.refresh_access_token()
            except (requests.RequestException, ValueError) as e:
                # `refresh_access_token` only records failure in `integration.errors` when LinkedIn
                # answers with a parseable body; a network error or an HTML error page escapes here.
                raise IntegrationAccountListingError(
                    "Could not reach LinkedIn to refresh the credentials for this integration. "
                    "Please try again in a few minutes."
                ) from e
        if integration.errors == ERROR_TOKEN_REFRESH_FAILED or not integration.access_token:
            raise IntegrationAccountListingError(
                "Could not refresh the LinkedIn credentials. Please reconnect your LinkedIn account."
            )

        client = LinkedinPagesClient(integration.access_token, api_version=self.default_version)
        try:
            organizations = client.list_administered_organizations()
        except LinkedinPagesApiError as e:
            if e.api_status_code in (401, 403):
                raise IntegrationAccountListingError(
                    "LinkedIn rejected the credentials for this integration. Please reconnect your LinkedIn account "
                    "and make sure it administers the pages you want to sync."
                ) from e
            raise
        except LinkedinPagesDailyRateLimitError as e:
            raise IntegrationAccountListingError(
                "LinkedIn's daily request limit for this app has been reached. Please try again tomorrow."
            ) from e
        except (LinkedinPagesRetryableError, requests.RequestException) as e:
            raise IntegrationAccountListingError(
                "LinkedIn is having trouble responding right now. Please try again in a few minutes."
            ) from e

        return [
            IntegrationAccount(value=organization.urn, display_name=organization.name) for organization in organizations
        ]

    def get_schemas(
        self,
        config: LinkedinPagesSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Only the statistics finders advertise incremental fields — see settings.py.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: LinkedinPagesSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.linkedin_pages_integration_id:
            return False, "A connected LinkedIn account is required"

        try:
            integration = self.get_linkedin_integration(config.linkedin_pages_integration_id, team_id)
        except Exception as e:
            capture_exception(e)
            return False, "The connected LinkedIn account could not be found. Please reconnect it."

        if not integration.access_token:
            return False, "The connected LinkedIn account has no access token. Please reconnect it."

        is_valid, status = probe_credentials(
            integration.access_token,
            api_version=self.resolve_api_version(api_version),
        )
        if is_valid:
            return True, None

        # A 403 means the token itself is genuine but this member lacks the organization-admin
        # scope. That is a per-table problem, so it must not block source creation.
        if status == 403:
            if schema_name is None:
                return True, None
            return False, (
                "LinkedIn denied access to this table. The connected account must administer the page, and PostHog "
                "needs the page admin and page posts permissions. Reconnect and grant both."
            )

        return False, "LinkedIn rejected the connected account. Please reconnect it."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LinkedinPagesResumeConfig]:
        # Endpoints store different cursor shapes (a window start vs a page token), so keep their
        # resume slots apart — a retry that switches endpoints must not load the other's state.
        return ResumableSourceManager[LinkedinPagesResumeConfig](inputs, LinkedinPagesResumeConfig).with_namespace(
            inputs.schema_name
        )

    def source_for_pipeline(
        self,
        config: LinkedinPagesSourceConfig,
        resumable_source_manager: ResumableSourceManager[LinkedinPagesResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        integration = self.get_linkedin_integration(config.linkedin_pages_integration_id, inputs.team_id)

        if not integration.access_token:
            raise ValueError(f"LinkedIn Pages access token not found for job {inputs.job_id}")

        return linkedin_pages_source(
            access_token=integration.access_token,
            organization_ids=config.organization_ids,
            endpoint=inputs.schema_name,
            resumable_source_manager=resumable_source_manager,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            api_version=self.resolve_api_version(inputs.api_version),
        )
