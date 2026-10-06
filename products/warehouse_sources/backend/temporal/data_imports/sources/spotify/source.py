from typing import Any, Optional, cast

from posthog.models.integration import Integration, OauthIntegration

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import CursorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.spotify import (
    SpotifySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.spotify.settings import (
    ACCOUNTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    RECENTLY_PLAYED,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.spotify.spotify import (
    ALL_ACCOUNTS_UNREADABLE,
    SpotifyAccount,
    SpotifyPlaysCursor,
    accounts_source,
    recently_played_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

SPOTIFY_INTEGRATION_KIND = "spotify"
APP_NOT_CONFIGURED = "Spotify is not set up on this PostHog instance."


@SourceRegistry.register
class SpotifySource(SimpleSource[SpotifySourceConfig], CursorSource[SpotifyPlaysCursor]):
    api_docs_url = "https://developer.spotify.com/documentation/web-api"

    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SPOTIFY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SPOTIFY,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            keywords=["music", "listening history"],
            label="Spotify",
            releaseStatus=ReleaseStatus.ALPHA,
            featureFlag="dwh-spotify",
            caption=(
                "Sync the listening history of every teammate who connects their Spotify account.\n\n"
                "This source has no credentials of its own. After you create it, each teammate opens its "
                "**Configuration** tab and connects their own account.\n\n"
                "Spotify keeps the last 50 plays for an account. Set the `recently_played` table to sync "
                "every hour or faster, and keep it on incremental sync, so that no plays are lost."
            ),
            iconPath="/static/services/spotify.png",
            memberIntegrationKind=SPOTIFY_INTEGRATION_KIND,
            fields=cast(list[FieldType], []),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.spotify.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            ALL_ACCOUNTS_UNREADABLE: (
                "None of the connected Spotify accounts could be read. Ask each person to reconnect their "
                "account from this source's Configuration tab."
            ),
            "Spotify app not configured": APP_NOT_CONFIGURED,
        }

    def get_schemas(
        self,
        config: SpotifySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Merge only, because a run that fails before its cursor is stored reads the same plays again.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=[RECENTLY_PLAYED])

    def validate_credentials(
        self,
        config: SpotifySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # Teammates connect their accounts after the source exists, so only the OAuth app can be checked.
        try:
            OauthIntegration.oauth_config_for_kind(SPOTIFY_INTEGRATION_KIND)
        except NotImplementedError:
            return False, APP_NOT_CONFIGURED
        return True, None

    def cursor_class(self) -> type[SpotifyPlaysCursor]:
        return SpotifyPlaysCursor

    def merge_cursors(self, current: SpotifyPlaysCursor, candidate: SpotifyPlaysCursor) -> SpotifyPlaysCursor:
        # A run stages only the accounts it read new plays from. The other accounts keep their position.
        merged = dict(current.newest_played_at_ms)
        for account_id, played_at_ms in candidate.newest_played_at_ms.items():
            merged[account_id] = max(played_at_ms, merged.get(account_id, played_at_ms))
        return SpotifyPlaysCursor(newest_played_at_ms=merged)

    def source_for_pipeline(self, config: SpotifySourceConfig, inputs: SourceInputs) -> SourceResponse:
        integrations = list(
            Integration.objects.filter(team_id=inputs.team_id, kind=SPOTIFY_INTEGRATION_KIND)
            .select_related("created_by")
            .order_by("id")
        )

        if inputs.schema_name == ACCOUNTS:
            return accounts_source([_account_row(integration) for integration in integrations])

        if inputs.schema_name != RECENTLY_PLAYED:
            raise ValueError(f"Unknown Spotify table: {inputs.schema_name}")

        manager = self.get_cursor_manager(inputs)
        return recently_played_source(
            accounts=self._readable_accounts(integrations, inputs),
            # A full refresh rebuilds the table, so it reads every account from the start of its window.
            cursor=manager.load() if inputs.should_use_incremental_field else None,
            stage_cursor=manager.stage,
            logger=inputs.logger,
        )

    def _readable_accounts(self, integrations: list[Integration], inputs: SourceInputs) -> list[SpotifyAccount]:
        accounts: list[SpotifyAccount] = []
        for integration in integrations:
            oauth_integration = OauthIntegration(integration)
            if oauth_integration.access_token_expired():
                oauth_integration.refresh_access_token()
            account_id = integration.integration_id
            access_token = integration.access_token
            if integration.errors or not account_id or not access_token:
                inputs.logger.warning(
                    "Skipping a Spotify account whose access expired. Its owner needs to reconnect it.",
                    account_id=account_id,
                )
                continue
            accounts.append(SpotifyAccount(account_id=account_id, access_token=access_token))

        # A source with accounts where none can be refreshed is broken. A source with no accounts yet is not.
        if integrations and not accounts:
            raise ValueError(ALL_ACCOUNTS_UNREADABLE)
        return accounts


def _account_row(integration: Integration) -> dict[str, Any]:
    connected_by = integration.created_by
    return {
        "account_id": integration.integration_id,
        "display_name": integration.display_name,
        "connected_by_email": connected_by.email if connected_by else None,
        "connected_by_name": connected_by.get_full_name() if connected_by else None,
        "connected_at": integration.created_at,
    }
