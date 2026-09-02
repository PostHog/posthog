from typing import Optional, cast

import structlog

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
)

from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, INSTAGRAM_OAUTH_SCOPE, InstagramIntegration

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.instagram import (
    InstagramSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instagram.instagram import (
    AUTH_ERROR_PREFIX,
    PERMISSION_ERROR_PREFIX,
    InstagramAPIError,
    InstagramAuthError,
    InstagramPermissionError,
    InstagramResumeConfig,
    instagram_source,
    list_professional_accounts,
    validate_credentials as validate_instagram_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instagram.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)


@SourceRegistry.register
class InstagramSource(ResumableSource[InstagramSourceConfig, InstagramResumeConfig], OAuthMixin):
    api_docs_url = "https://developers.facebook.com/docs/instagram-platform"
    # Meta pins the Graph API by URL path segment and keeps each version alive for
    # roughly two years, so the pin is a real choice rather than a constant.
    supported_versions = ("v22.0", "v23.0", "v26.0")
    default_version = "v26.0"

    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INSTAGRAM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INSTAGRAM,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Instagram",
            caption="""Pull posts, stories, comments and insights from an Instagram professional (Business or Creator) account into the PostHog Data warehouse.

Connect your Instagram account, then pick the professional account you want to sync. The account has to be linked to a Facebook page, and you'll be asked to grant access to that page along with Instagram insights and comments.""",
            iconPath="/static/services/instagram.png",
            docsUrl="https://posthog.com/docs/cdp/sources/instagram",
            keywords=["ig", "meta", "social"],
            releaseStatus=ReleaseStatus.ALPHA,
            featureFlag="dwh-instagram",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="instagram_integration_id",
                        label="Instagram account",
                        required=True,
                        kind="instagram",
                        requiredScopes=INSTAGRAM_OAUTH_SCOPE,
                    ),
                    SourceFieldOauthAccountSelectConfig(
                        name="instagram_account_id",
                        label="Instagram professional account",
                        integrationField="instagram_integration_id",
                        integrationKind="instagram",
                        required=True,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2024-01-01",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            AUTH_ERROR_PREFIX: (
                "The Instagram connection has expired. Reconnect your Instagram account to keep syncing."
            ),
            PERMISSION_ERROR_PREFIX: (
                "The Instagram connection is missing permissions this sync needs. Reconnect it and grant "
                "access to your page, Instagram insights and comments."
            ),
            "Failed to refresh the Instagram connection": (
                "The Instagram connection could not be refreshed. Reconnect your Instagram account."
            ),
            # The source still points at an `instagram_integration_id` whose Integration row is gone
            # (deleted or de-authorized), which `get_oauth_integration` reports as a ValueError.
            # Retrying can't bring the row back; only reconnecting can.
            "Integration not found": (
                "The Instagram connection for this source no longer exists. Reconnect your Instagram account."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.instagram.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: InstagramSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def _access_token(self, integration_id: int, team_id: int) -> str:
        """An access token Meta will still accept.

        Meta issues no refresh token, so a long-lived token is swapped for a fresh one on use.
        `refresh_access_token` is a no-op while the current token has more than 7 days left.
        """
        integration = self.get_oauth_integration(integration_id, team_id)
        InstagramIntegration(integration).refresh_access_token()

        if integration.errors == ERROR_TOKEN_REFRESH_FAILED or not integration.access_token:
            raise ValueError("Failed to refresh the Instagram connection")

        return integration.access_token

    def get_oauth_accounts(
        self, integration_id: int, team_id: int, search: str | None = None
    ) -> list[IntegrationAccount]:
        # A Facebook user's pages are few, so `search` is ignored here and the endpoint filters the list.
        try:
            access_token = self._access_token(integration_id, team_id)
        except ValueError as e:
            raise IntegrationAccountListingError(
                "The linked Instagram connection could not be used. Please reconnect your Instagram account."
            ) from e

        try:
            accounts = list_professional_accounts(
                access_token=access_token,
                api_version=self.default_version,
                logger=logger,
            )
        except (InstagramAuthError, InstagramPermissionError) as e:
            raise IntegrationAccountListingError(
                "Instagram rejected this connection. Reconnect your Instagram account and grant access to "
                "the page your professional account is linked to."
            ) from e
        except InstagramAPIError as e:
            # Throttling or a Graph API blip. Neither is a bug, so surface it as something the user
            # can retry rather than a 500 that pages us.
            raise IntegrationAccountListingError(
                "Instagram is having trouble responding right now. Please try again in a few minutes."
            ) from e

        return [
            IntegrationAccount(
                value=account["id"],
                display_name=account.get("username") or account.get("name") or "Instagram account",
                secondary_text=account.get("page_name"),
            )
            for account in accounts
        ]

    def validate_credentials(
        self,
        config: InstagramSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            access_token = self._access_token(config.instagram_integration_id, team_id)
        except ValueError:
            return False, "Connect an Instagram account before syncing."

        return validate_instagram_credentials(
            access_token=access_token,
            api_version=self.resolve_api_version(api_version),
            logger=logger,
            instagram_account_id=config.instagram_account_id,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[InstagramResumeConfig]:
        # Each endpoint checkpoints a URL built for its own edge, so a retry that lands on
        # a different table must not pick up the previous table's cursor.
        return ResumableSourceManager[InstagramResumeConfig](
            inputs, InstagramResumeConfig, namespace=inputs.schema_name
        )

    def source_for_pipeline(
        self,
        config: InstagramSourceConfig,
        resumable_source_manager: ResumableSourceManager[InstagramResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return instagram_source(
            access_token=self._access_token(config.instagram_integration_id, inputs.team_id),
            api_version=self.resolve_api_version(inputs.api_version),
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            instagram_account_id=config.instagram_account_id,
            start_date=config.start_date,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
