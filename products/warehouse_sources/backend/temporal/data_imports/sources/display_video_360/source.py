from typing import TYPE_CHECKING, Any, Optional, cast

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

from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.display_video_360.display_video_360 import (
    DISPLAY_VIDEO_SCOPES,
    DisplayVideo360ResumeConfig,
    display_video_360_source,
    validate_credentials as validate_display_video_360_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.display_video_360.settings import (
    DISPLAY_VIDEO_360_ENDPOINTS,
    DISPLAY_VIDEO_API_VERSION,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    REPORT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.displayvideo360 import (
    DisplayVideo360SourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


@SourceRegistry.register
class DisplayVideo360Source(ResumableSource[DisplayVideo360SourceConfig, DisplayVideo360ResumeConfig], OAuthMixin):
    supported_versions = (DISPLAY_VIDEO_API_VERSION,)
    default_version = DISPLAY_VIDEO_API_VERSION
    api_docs_url = "https://developers.google.com/display-video/api/reference/rest"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DISPLAYVIDEO360

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DISPLAY_VIDEO360,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["dv360", "doubleclick bid manager", "google display video"],
            label="Display & Video 360",
            caption="""Connect Display & Video 360 to sync your partners, advertisers, campaigns, insertion orders, line items, creatives, and daily performance reports into the PostHog Data warehouse.

Pick how PostHog should authenticate:

- **Google account** - click Connect and grant the `display-video` and `doubleclickbidmanager` scopes. The account you connect needs access to the partner in Display & Video 360.
- **Service account key** - paste the JSON key file. Enable both the **Display & Video 360 API** and the **Bid Manager API** on the service account's Google Cloud project, and add its email as a Display & Video 360 user with access to the partner.

Performance tables are generated as Bid Manager reports, so they only reach as far back as Display & Video 360 retains reporting data.""",
            iconPath="/static/services/display_video_360.png",
            docsUrl="https://posthog.com/docs/cdp/sources/display-video-360",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="auth_type",
                        label="Authentication",
                        required=True,
                        defaultValue="oauth",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="Google account",
                                value="oauth",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldOauthConfig(
                                            name="display_video_360_integration_id",
                                            label="Display & Video 360 account",
                                            required=False,
                                            kind="display-video-360",
                                            requiredScopes=" ".join(DISPLAY_VIDEO_SCOPES),
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="Service account key",
                                value="service_account",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="service_account_key",
                                            label="Service account JSON key",
                                            type=SourceFieldInputConfigType.TEXTAREA,
                                            required=False,
                                            placeholder='{"type": "service_account", ...}',
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="partner_id",
                        label="Partner ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="123456",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="advertiser_ids",
                        label="Advertiser IDs",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Leave blank to sync every advertiser under the partner",
                        secret=False,
                    ),
                ],
            ),
        )

    @property
    def connection_host_fields(self) -> list[str]:
        # `partner_id` and `advertiser_ids` decide which Google account the stored credential acts
        # on. Changing either must re-require the credential so an editor who can't read it can't
        # silently repoint the connection at a different partner or advertiser scope.
        return ["partner_id", "advertiser_ids"]

    def has_preserved_row_backed_credentials(
        self, source_model: "ExternalDataSource", incoming_job_inputs: dict[str, Any]
    ) -> bool:
        # In OAuth mode the Google grant lives in an `Integration` row, not in `job_inputs`, so the
        # generic preserved-credentials check finds no secret and the `connection_host_fields` gate
        # above would let an editor repoint `partner_id`/`advertiser_ids` at another DV360 account
        # while silently reusing someone else's retained refresh token. Treat the row's token as
        # preserved unless this update connects a *different* account, which is an explicit
        # re-authorization by someone who actually holds that grant.
        existing_job_inputs = source_model.job_inputs or {}
        existing_auth = existing_job_inputs.get("auth_type")
        if not isinstance(existing_auth, dict) or existing_auth.get("selection") != "oauth":
            return False

        existing_integration_id = existing_auth.get("display_video_360_integration_id")
        if not existing_integration_id:
            return False

        incoming_auth = incoming_job_inputs.get("auth_type")
        incoming_integration_id = (
            incoming_auth.get("display_video_360_integration_id") if isinstance(incoming_auth, dict) else None
        )
        if not incoming_integration_id:
            return True
        return str(incoming_integration_id) == str(existing_integration_id)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Google rejected your Display & Video 360 credentials. Reconnect your Google account or update the service account key.",
            "403 Client Error": "Your credentials cannot read Display & Video 360. Add the connected account or service account as a Display & Video 360 user with partner access, and enable both the Display & Video 360 API and the Bid Manager API.",
            # google-auth raises this while refreshing when a refresh token has been revoked or a
            # service account key has been rotated away. No retry can recover it.
            "invalid_grant": "Your Display & Video 360 connection has expired or been revoked. Reconnect your Google account.",
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT": "The credentials are missing the Display & Video 360 or Bid Manager scope. Reconnect and grant both scopes.",
            "The service account key": "The service account JSON key could not be read. Paste the complete key file and reconnect.",
            # Raised before any child request when a configured advertiser belongs to a different
            # partner. Only the customer can fix it, so retrying cannot help.
            "not under Display & Video 360 partner": "One or more of the advertiser IDs you entered are not under the configured partner. Check the advertiser IDs and the partner ID.",
            # Raised by `get_oauth_integration` when the source still points at an integration row
            # that has since been deleted, or was saved before an account was connected. No retry
            # can recreate it.
            "Missing integration ID": "Connect a Google account with access to Display & Video 360 before syncing.",
            "Integration not found": "The connected Display & Video 360 account no longer exists. Connect it again.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.display_video_360.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DisplayVideo360SourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=DISPLAY_VIDEO_360_ENDPOINTS[endpoint].supports_incremental,
                supports_append=DISPLAY_VIDEO_360_ENDPOINTS[endpoint].supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=(
                    "Generated as a Bid Manager report, so history only reaches as far back as your "
                    "Display & Video 360 reporting retention"
                    if endpoint in REPORT_ENDPOINTS
                    else None
                ),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [schema for schema in schemas if schema.name in names_set]

        return schemas

    def _resolve_integration(self, config: DisplayVideo360SourceConfig, team_id: int) -> Integration | None:
        """The connected Google account, or None when the source authenticates with a service account key."""
        auth = config.auth_type
        if auth is None or auth.selection != "oauth":
            return None
        integration_id = auth.display_video_360_integration_id
        if not integration_id:
            raise ValueError("Missing integration ID")
        return self.get_oauth_integration(integration_id, team_id)

    def validate_credentials(
        self,
        config: DisplayVideo360SourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            integration = self._resolve_integration(config, team_id)
        except ValueError:
            return False, "Connect a Google account with access to Display & Video 360 to continue."
        return validate_display_video_360_credentials(config, self.resolve_api_version(api_version), integration)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DisplayVideo360ResumeConfig]:
        # Entity page tokens and report date windows share one dataclass but are never
        # interchangeable, so keep each schema's resume state in its own namespace.
        return ResumableSourceManager[DisplayVideo360ResumeConfig](
            inputs, DisplayVideo360ResumeConfig, namespace=inputs.schema_name
        )

    def source_for_pipeline(
        self,
        config: DisplayVideo360SourceConfig,
        resumable_source_manager: ResumableSourceManager[DisplayVideo360ResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return display_video_360_source(
            config=config,
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            integration=self._resolve_integration(config, inputs.team_id),
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
