from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    AuthConfigBase,
    BearerTokenAuth,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.resend import ResendSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.resend.oauth import (
    ResendIntegrationAuth,
    resolve_resend_oauth_token,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.resend.resend import (
    ResendResumeConfig,
    resend_source,
    validate_credentials as validate_resend_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.resend.settings import ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ResendSource(ResumableSource[ResendSourceConfig, ResendResumeConfig], OAuthMixin):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://resend.com/docs/api-reference/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RESEND

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RESEND,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Resend",
            releaseStatus=ReleaseStatus.GA,
            caption="""Connect Resend to pull your Resend data into the PostHog Data warehouse. Connect with OAuth, or paste a Resend API key.

Either way, the connection needs **full access** so the following resources can be read:
- Audiences
- Broadcasts
- Contacts
- Domains
- Emails
""",
            iconPath="/static/services/resend.png",
            docsUrl="https://posthog.com/docs/cdp/sources/resend",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication type",
                        required=True,
                        defaultValue="api_key",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="API key",
                                value="api_key",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="api_key",
                                            label="API key",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="re_...",
                                            caption="Create a full-access API key in your [Resend API keys settings](https://resend.com/api-keys).",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="OAuth",
                                value="oauth",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldOauthConfig(
                                            name="resend_integration_id",
                                            label="Resend account",
                                            required=False,
                                            kind="resend",
                                            requiredScopes="full_access",
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.resend.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ResendSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Resend's API does not expose server-side filters on created_at; sync as
        # full-refresh only. Within-sync resumption is handled by ResumableSource.
        schemas = [
            SourceSchema(name=endpoint, supports_incremental=False, supports_append=False, incremental_fields=[])
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def _probe_token(self, config: ResendSourceConfig, team_id: int) -> str:
        """Resolve the current bearer token for the selected auth method, used for validation."""
        if config.auth_method.selection == "api_key":
            if not config.auth_method.api_key:
                raise ValueError("Missing Resend API key")
            return config.auth_method.api_key

        integration_id = config.auth_method.resend_integration_id
        if not integration_id:
            raise ValueError("Missing Resend integration ID")
        self.get_oauth_integration(integration_id, team_id)  # ownership check → non-retryable ValueError
        return resolve_resend_oauth_token(integration_id, team_id)

    def _build_auth(self, config: ResendSourceConfig, team_id: int) -> AuthConfigBase:
        """Build the transport auth. API key → static bearer; OAuth → an auth that re-mints the
        access token through the integration row (rotation-safe) so long syncs never see a 401."""
        if config.auth_method.selection == "api_key":
            if not config.auth_method.api_key:
                raise ValueError("Missing Resend API key")
            return BearerTokenAuth(config.auth_method.api_key)

        integration_id = config.auth_method.resend_integration_id
        if not integration_id:
            raise ValueError("Missing Resend integration ID")
        self.get_oauth_integration(integration_id, team_id)  # ownership check → non-retryable ValueError
        token = resolve_resend_oauth_token(integration_id, team_id)
        return ResendIntegrationAuth(integration_id, team_id, token)

    def validate_credentials(
        self,
        config: ResendSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            token = self._probe_token(config, team_id)
        except ValueError as e:
            return False, str(e)

        if validate_resend_credentials(token):
            return True, None

        if config.auth_method.selection == "oauth":
            return False, "Your Resend connection is invalid or expired. Please reconnect it."
        return False, "Invalid Resend API key"

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.resend.com": (
                "Your Resend credentials are invalid or expired. Please reconnect the source or generate a new API key."
            ),
            "403 Client Error: Forbidden for url: https://api.resend.com": (
                "Your Resend connection does not have the required permissions. Grant full access and reconnect."
            ),
            # Deterministic credential/config errors from OAuthMixin and the auth builders — the
            # integration row is gone or unconfigured, so retrying can never succeed. Match on the
            # stable prefix so the volatile integration ID is ignored.
            "Missing Resend integration ID": "Resend integration is not configured. Please reconnect your Resend account.",
            "Integration not found": "The linked Resend integration no longer exists. Please reconnect your Resend account.",
            "Resend access token not found": "Resend OAuth access token is missing. Please reconnect your Resend account.",
            # Resend rejects the well-formed list request with a 400 when the connected account
            # can't access the Audiences/Contacts API (the Marketing/Audiences feature isn't enabled,
            # or the key lacks full access). Retrying the identical request can't fix an account-level
            # restriction. Scope the match to the audiences path so a 400 from another endpoint (which
            # could be our bug) stays retryable and visible.
            "400 Client Error: Bad Request for url: https://api.resend.com/audiences": (
                "Resend rejected the request to sync your Audiences/Contacts. This usually means the connected "
                "Resend account can't access the Audiences API — enable Audiences in Resend and grant the API key "
                "full access, or unselect the Audiences and Contacts tables to keep syncing your other Resend data."
            ),
            # Resend rejects the well-formed list request with a 400 when the connected account
            # can't access the Broadcasts API (the Marketing/Audiences feature isn't enabled, or
            # the key lacks full access to broadcasts). Retrying the identical request can't fix an
            # account-level restriction. Scope the match to the broadcasts path so a 400 from another
            # endpoint (which could be our bug) stays retryable and visible.
            "400 Client Error: Bad Request for url: https://api.resend.com/broadcasts": (
                "Resend rejected the request to sync your Broadcasts. This usually means the connected Resend "
                "account can't access the Broadcasts API — enable Broadcasts in Resend and grant the API key full "
                "access, or unselect the Broadcasts table to keep syncing your other Resend data."
            ),
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ResendResumeConfig]:
        return ResumableSourceManager[ResendResumeConfig](inputs, ResendResumeConfig)

    def source_for_pipeline(
        self,
        config: ResendSourceConfig,
        resumable_source_manager: ResumableSourceManager[ResendResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return resend_source(
            auth=self._build_auth(config, inputs.team_id),
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
