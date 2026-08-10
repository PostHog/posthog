from typing import Any, Optional, cast

from rest_framework.exceptions import ValidationError

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

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googledrive import (
    GoogleDriveSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_drive.google_drive import (
    DRIVE_READONLY_SCOPES,
    GOOGLE_DRIVE_API_VERSION_V3,
    MISSING_SERVICE_ACCOUNT_KEY_ERROR,
    GoogleDriveAuth,
    GoogleDriveResumeConfig,
    google_drive_source,
    validate_credentials as validate_google_drive_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_drive.oauth import (
    MISSING_ACCESS_TOKEN_ERROR,
    MISSING_INTEGRATION_ID_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_drive.settings import (
    ENDPOINT_DESCRIPTIONS,
    GOOGLE_DRIVE_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GoogleDriveSource(ResumableSource[GoogleDriveSourceConfig, GoogleDriveResumeConfig], OAuthMixin):
    api_docs_url = "https://developers.google.com/workspace/drive/api/reference/rest/v3"
    # Drive's version is a path segment (`/drive/v3/`) and v2 is retired, so v3 is the only pin.
    supported_versions = (GOOGLE_DRIVE_API_VERSION_V3,)
    default_version = GOOGLE_DRIVE_API_VERSION_V3

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEDRIVE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_DRIVE,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            label="Google Drive",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["gdrive", "google workspace"],
            caption="""Sync your Google Drive file inventory, shared drives, and shared drive access grants. This reads file metadata only and never downloads file contents.

Connect a Google account and grant read-only access to Drive. If you'd rather not tie the connection to one person's account, switch the authentication type and paste a service account key.""",
            iconPath="/static/services/google_drive.png",
            docsUrl="https://posthog.com/docs/cdp/sources/google-drive",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication type",
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
                                            name="google_drive_integration_id",
                                            label="Google Drive account",
                                            required=False,
                                            kind="google-drive",
                                            requiredScopes=" ".join(DRIVE_READONLY_SCOPES),
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
                                            caption="Paste the whole JSON key file. The service account only sees files shared with its email address, unless you also fill in the field below.",
                                            secret=True,
                                        ),
                                        SourceFieldInputConfig(
                                            name="impersonated_user_email",
                                            label="Impersonated user email",
                                            type=SourceFieldInputConfigType.EMAIL,
                                            required=False,
                                            placeholder="you@yourcompany.com",
                                            caption="Optional. With domain-wide delegation set up, the service account reads Drive as this user.",
                                            secret=False,
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="drive_id",
                        label="Shared drive ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="",
                        caption="Optional. Limits the files table to one shared drive. Leave empty to sync every file the credentials can see.",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.google_drive.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Google Drive rejected these credentials. They may have been revoked or rotated — reconnect the source with a fresh key or refresh token.",
            "403 Client Error": "These credentials cannot read Drive. Grant the drive.readonly scope, enable the Google Drive API in the Google Cloud project, and reconnect.",
            # Raised while getting the access token: a rotated service account key, delegation that
            # was withdrawn, or a revoked Google connection. None of it recovers on retry.
            "Google Drive authentication failed": "PostHog could not get an access token for Google Drive. Reconnect your Google account, or check the service account key.",
            MISSING_SERVICE_ACCOUNT_KEY_ERROR: "No Google Drive service account key is configured. Please update the source configuration.",
            # Deterministic credential errors from the OAuth path: the integration row is missing or
            # holds no token, so retrying can never succeed. Match on the stable prefix so the
            # volatile integration ID is ignored.
            MISSING_INTEGRATION_ID_ERROR: "No Google account is connected. Please reconnect the source.",
            "Integration not found": "The linked Google account no longer exists in PostHog. Please reconnect the source.",
            MISSING_ACCESS_TOKEN_ERROR: "The Google Drive connection has no access token. Please reconnect the source.",
            "Invalid Google Drive service account key": None,
        }

    def get_retryable_errors(self) -> set[str]:
        # Drive reports quota exhaustion as a 403; the transport retries it with backoff and only
        # re-raises once the budget is spent, so Temporal retrying the activity is the right outcome.
        return {"Google Drive rate limit"}

    def job_inputs_add_connection_host(
        self, incoming_job_inputs: dict[str, Any], existing_job_inputs: dict[str, Any]
    ) -> bool:
        """Guard the delegated identity the same way a connection host is guarded.

        With domain-wide delegation the service account key can read Drive as any user in the
        workspace, and `impersonated_user_email` is what picks that user. The generic update merge
        carries an omitted `service_account_key` over from the stored config, so without this an
        editor who never had the key could point it at a different principal and sync that person's
        Drive. The identity is the credential's target, so changing it requires re-entering the key.

        Returns ``False`` (no new connection host) in every case — a change that needs the key
        re-entered is rejected here, with a message about the identity rather than about a host.
        """
        incoming_auth = incoming_job_inputs.get("auth_method")
        existing_auth = existing_job_inputs.get("auth_method")
        if not isinstance(incoming_auth, dict) or not isinstance(existing_auth, dict):
            return False

        # Only the preserved-key path is exposed. A `selection` switch replaces the whole container,
        # dropping the stored key, so the editor has to supply one anyway.
        if existing_auth.get("selection") != "service_account" or incoming_auth.get("selection") != "service_account":
            return False
        if not existing_auth.get("service_account_key"):
            return False

        incoming_email = incoming_auth.get("impersonated_user_email") or None
        if incoming_email is None or incoming_email == (existing_auth.get("impersonated_user_email") or None):
            # Unchanged, or cleared back to the service account's own identity — no escalation.
            return False
        if incoming_auth.get("service_account_key"):
            # Re-entered in the same request, so the editor already holds the key.
            return False

        raise ValidationError("Changing the impersonated user requires re-entering the service account JSON key.")

    def _get_auth(self, config: GoogleDriveSourceConfig, team_id: int) -> GoogleDriveAuth:
        if config.auth_method.selection == "oauth":
            integration_id = config.auth_method.google_drive_integration_id
            if not integration_id:
                raise ValueError(MISSING_INTEGRATION_ID_ERROR)
            # Ownership check up front, so a deleted or foreign integration fails here with a stable
            # error instead of at the first request. The token itself is read later, per request.
            self.get_oauth_integration(integration_id, team_id)
            return GoogleDriveAuth(integration_id=integration_id, team_id=team_id)

        if not config.auth_method.service_account_key:
            raise ValueError(MISSING_SERVICE_ACCOUNT_KEY_ERROR)
        return GoogleDriveAuth(
            service_account_key=config.auth_method.service_account_key,
            impersonated_user_email=config.auth_method.impersonated_user_email or None,
        )

    def get_schemas(
        self,
        config: GoogleDriveSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=name,
                supports_incremental=endpoint.supports_incremental,
                supports_append=endpoint.supports_incremental,
                incremental_fields=endpoint.incremental_fields,
                description=ENDPOINT_DESCRIPTIONS.get(name),
                detected_primary_keys=list(endpoint.primary_keys),
            )
            for name, endpoint in GOOGLE_DRIVE_ENDPOINTS.items()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [schema for schema in schemas if schema.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: GoogleDriveSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            auth = self._get_auth(config, team_id)
        except ValueError as e:
            # The OAuth mixin's "Integration not found: <id>" carries a volatile ID, so match on the
            # curated prefixes rather than looking the raw message up as a key.
            raw = str(e)
            for pattern, friendly in self.get_non_retryable_errors().items():
                if friendly and pattern in raw:
                    return False, friendly
            return False, raw

        return validate_google_drive_credentials(auth, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GoogleDriveResumeConfig]:
        return ResumableSourceManager[GoogleDriveResumeConfig](inputs, GoogleDriveResumeConfig)

    def source_for_pipeline(
        self,
        config: GoogleDriveSourceConfig,
        resumable_source_manager: ResumableSourceManager[GoogleDriveResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return google_drive_source(
            auth=self._get_auth(config, inputs.team_id),
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            source_logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            drive_id=config.drive_id or None,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
