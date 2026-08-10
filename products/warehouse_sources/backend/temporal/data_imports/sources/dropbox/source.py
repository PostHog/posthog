from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
)

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
from products.warehouse_sources.backend.temporal.data_imports.sources.dropbox.dropbox import (
    DropboxCredentials,
    DropboxResumeConfig,
    check_endpoint_access,
    dropbox_source,
    validate_credentials as validate_dropbox_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dropbox.settings import (
    DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SHOULD_SYNC_DEFAULT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dropbox import (
    DropboxSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DropboxSource(ResumableSource[DropboxSourceConfig, DropboxResumeConfig], OAuthMixin):
    api_docs_url = "https://www.dropbox.com/developers/documentation/http/documentation"
    supported_versions = ("v2",)
    default_version = "v2"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DROPBOX

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.dropboxapi.com/2/": "Dropbox rejected the access token. Reconnect your Dropbox account.",
            "403 Client Error: Forbidden for url: https://api.dropboxapi.com/2/": "Your Dropbox connection cannot read this table. The team tables need a Dropbox Business team connection.",
            "409 Client Error: Conflict for url: https://api.dropboxapi.com/2/": "Dropbox rejected the request. Check that the folder path exists and that the account can reach it.",
            # Deterministic credential errors from OAuthMixin — the integration row is gone or was
            # never set, so retrying can never succeed.
            "Missing integration ID": "Dropbox is not connected. Reconnect your Dropbox account.",
            "Integration not found": "The linked Dropbox connection no longer exists. Reconnect your Dropbox account.",
            "Dropbox access token not found": "The Dropbox access token is missing. Reconnect your Dropbox account.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DROPBOX,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            label="Dropbox",
            caption="""Connect Dropbox to pull file, folder, and sharing metadata into the PostHog Data warehouse.

Connect your Dropbox account and authorize PostHog. It asks for read-only access to your account info, file metadata, and sharing metadata.

The team tables need a Dropbox Business team connection, which PostHog does not request, so they stay off by default.""",
            iconPath="/static/services/dropbox.png",
            docsUrl="https://posthog.com/docs/cdp/sources/dropbox",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="dropbox_integration_id",
                        label="Dropbox account",
                        required=True,
                        kind="dropbox",
                        requiredScopes="account_info.read files.metadata.read sharing.read",
                    ),
                    SourceFieldInputConfig(
                        name="folder_path",
                        label="Folder path (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="/Reports",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="team_member_id",
                        label="Team member ID (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="dbmid:...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="root_namespace_id",
                        label="Root namespace ID (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.dropbox.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DropboxSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            descriptions=DESCRIPTIONS,
            should_sync_default=SHOULD_SYNC_DEFAULT,
        )

    def _credentials(self, config: DropboxSourceConfig, team_id: int) -> DropboxCredentials:
        integration = self.get_oauth_integration(config.dropbox_integration_id, team_id)
        # The id alone is attacker-controllable within a project, so pin the provider before reading
        # the token: otherwise pointing this source at, say, a Slack integration of the same team
        # would send that provider's bearer token to Dropbox.
        if integration.kind != "dropbox":
            raise ValueError(f"Integration not found: {config.dropbox_integration_id}")
        if not integration.access_token:
            raise ValueError("Dropbox access token not found")

        return DropboxCredentials(
            access_token=integration.access_token,
            team_member_id=config.team_member_id,
            root_namespace_id=config.root_namespace_id,
        )

    def validate_credentials(
        self,
        config: DropboxSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            credentials = self._credentials(config, team_id)
        except ValueError:
            return False, "Connect a Dropbox account to continue."

        return validate_dropbox_credentials(credentials)

    def get_endpoint_permissions(
        self,
        config: DropboxSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        try:
            credentials = self._credentials(config, team_id)
        except ValueError:
            # Nothing to probe with yet. Reporting every table as reachable keeps the schema
            # picker usable; a genuinely broken connection is caught by validate_credentials.
            return dict.fromkeys(endpoints)

        return check_endpoint_access(credentials, endpoints)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DropboxResumeConfig]:
        return ResumableSourceManager[DropboxResumeConfig](inputs, DropboxResumeConfig)

    def source_for_pipeline(
        self,
        config: DropboxSourceConfig,
        resumable_source_manager: ResumableSourceManager[DropboxResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return dropbox_source(
            credentials=self._credentials(config, inputs.team_id),
            endpoint=inputs.schema_name,
            folder_path=config.folder_path,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
