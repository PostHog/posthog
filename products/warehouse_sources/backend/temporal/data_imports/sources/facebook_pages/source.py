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

from posthog.models.integration import FACEBOOK_PAGES_SCOPE

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccount,
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.facebook_pages.facebook_pages import (
    AUTH_ERROR_PREFIX,
    INTEGRATION_KIND,
    INVALID_PAGE_ID_ERROR,
    PERMISSION_ERROR_PREFIX,
    PROBE_LOGGER,
    TOKEN_REFRESH_ERROR_MESSAGE,
    FacebookPagesAuthError,
    FacebookPagesPermissionError,
    FacebookPagesResumeConfig,
    FacebookPagesRetryableError,
    FacebookPagesTokenRefreshError,
    facebook_pages_source,
    get_user_access_token,
    list_pages,
    validate_credentials as validate_facebook_pages_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.facebook_pages.settings import (
    DEFAULT_API_VERSION,
    ENDPOINTS,
    FACEBOOK_PAGES_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.facebookpages import (
    FacebookPagesSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FacebookPagesSource(ResumableSource[FacebookPagesSourceConfig, FacebookPagesResumeConfig], OAuthMixin):
    supported_versions = (DEFAULT_API_VERSION,)
    default_version = DEFAULT_API_VERSION
    api_docs_url = "https://developers.facebook.com/docs/graph-api/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FACEBOOKPAGES

    @property
    def connection_host_fields(self) -> list[str]:
        # page_id selects which Page the stored token reads from; changing it must require
        # re-entering the secrets so a preserved token can't be retargeted at another Page.
        return ["page_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FACEBOOK_PAGES,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Facebook Pages",
            keywords=["facebook", "meta", "graph api"],
            caption="""Pull your Facebook Page's profile, posts, videos, and daily insights into the PostHog Data warehouse.

Connect the Meta account that manages the Page, then pick the Page you want to sync. PostHog asks for read-only access to your Pages, their posts, and their insights.""",
            iconPath="/static/services/facebook_pages.png",
            docsUrl="https://posthog.com/docs/cdp/sources/facebook-pages",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="facebook_pages_integration_id",
                        label="Facebook account",
                        required=True,
                        kind=INTEGRATION_KIND,
                        requiredScopes=FACEBOOK_PAGES_SCOPE,
                    ),
                    SourceFieldOauthAccountSelectConfig(
                        name="page_id",
                        label="Facebook Page",
                        integrationField="facebook_pages_integration_id",
                        integrationKind=INTEGRATION_KIND,
                        required=True,
                        placeholder="Select a Page",
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            AUTH_ERROR_PREFIX: (
                "Facebook rejected the connected account. Please reconnect your Facebook Pages integration."
            ),
            PERMISSION_ERROR_PREFIX: (
                "The connected Meta account is missing a permission needed to sync this table. Reconnect your "
                "Facebook Pages integration and grant access to your Pages, their posts, and their insights."
            ),
            TOKEN_REFRESH_ERROR_MESSAGE: TOKEN_REFRESH_ERROR_MESSAGE,
            # A Page ID that isn't a Graph node ID can never produce a valid request, so the
            # job should stop rather than retry until it exhausts its attempts.
            INVALID_PAGE_ID_ERROR: (
                "The Facebook Page configured for this source is no longer valid. Please re-select the Page you "
                "want to sync."
            ),
            # The source still points at an Integration row the team no longer has, so
            # `get_oauth_integration` raises. Retrying can't bring the row back.
            "Integration not found": (
                "The Facebook Pages integration for this source no longer exists. Please reconnect it."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.facebook_pages.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: FacebookPagesSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=FACEBOOK_PAGES_ENDPOINTS[endpoint].description,
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def _access_token(self, integration_id: int, team_id: int) -> str:
        return get_user_access_token(self.get_oauth_integration(integration_id, team_id))

    def get_oauth_accounts(
        self, integration_id: int, team_id: int, search: str | None = None
    ) -> list[IntegrationAccount]:
        # A Meta user administers few Pages, so `search` is ignored here and the endpoint filters the list.
        try:
            access_token = self._access_token(integration_id, team_id)
        except ValueError as e:
            raise IntegrationAccountListingError(
                "The linked Facebook Pages integration could not be found. Please reconnect it."
            ) from e
        except FacebookPagesTokenRefreshError as e:
            raise IntegrationAccountListingError(str(e)) from e

        # capture=False for the same reason as the sync path: Page names are arbitrary customer
        # content the sample scrubber can't recognise. See get_rows.
        session = make_tracked_session(redact_values=(access_token,), capture=False)

        try:
            pages = list_pages(session, self.resolve_api_version(None), access_token, PROBE_LOGGER)
        except (FacebookPagesAuthError, FacebookPagesPermissionError) as e:
            raise IntegrationAccountListingError(
                "Facebook rejected the credentials for this integration. Please reconnect it and make sure the "
                "connected account can manage your Pages."
            ) from e
        except (FacebookPagesRetryableError, requests.RequestException) as e:
            # Throttling or a Meta-side blip that outlived the in-process retries. Neither is a bug,
            # so surface an actionable message rather than letting it escape as a 500.
            raise IntegrationAccountListingError(
                "Facebook is having trouble responding right now. Please try again in a few minutes."
            ) from e

        return [
            IntegrationAccount(
                value=str(page["id"]),
                display_name=page.get("name") or "Unnamed Page",
                badges=(page["category"],) if page.get("category") else (),
            )
            for page in pages
        ]

    def validate_credentials(
        self,
        config: FacebookPagesSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.facebook_pages_integration_id:
            return False, "Connect a Facebook account"
        if not config.page_id:
            return False, "Select the Facebook Page you want to sync"

        try:
            access_token = self._access_token(config.facebook_pages_integration_id, team_id)
        except (ValueError, FacebookPagesTokenRefreshError) as e:
            return False, str(e)

        return validate_facebook_pages_credentials(
            page_id=config.page_id,
            access_token=access_token,
            api_version=self.resolve_api_version(api_version),
            schema_name=schema_name,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FacebookPagesResumeConfig]:
        return ResumableSourceManager[FacebookPagesResumeConfig](inputs, FacebookPagesResumeConfig)

    def source_for_pipeline(
        self,
        config: FacebookPagesSourceConfig,
        resumable_source_manager: ResumableSourceManager[FacebookPagesResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return facebook_pages_source(
            page_id=config.page_id,
            access_token=self._access_token(config.facebook_pages_integration_id, inputs.team_id),
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            api_version=self.resolve_api_version(inputs.api_version),
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
