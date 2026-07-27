import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Optional

from django.db import models, transaction
from django.db.models import Q

import structlog
from prometheus_client import Counter

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED
from posthog.models.scoping import team_scope
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel, sane_repr

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import OAuth2Auth

logger = structlog.get_logger(__name__)

# The config-driven twin of `oauth_refresh_counter` in posthog.models.integration: a separate metric
# since the custom store refreshes off a row-stored client rather than a kind-keyed settings client.
custom_oauth2_refresh_counter = Counter(
    "warehouse_custom_oauth2_refresh",
    "Number of times a custom OAuth2 integration token refresh has been attempted",
    labelnames=["result"],
)

# Re-mint the access token slightly before its declared expiry so a token that's still
# valid at the check isn't rejected mid-flight. Same value as OAuth2Auth._TOKEN_EXPIRY_BUFFER —
# redeclared here rather than imported so the model module doesn't pull the HTTP transport
# stack onto the django.setup() model-load path.
_TOKEN_EXPIRY_BUFFER = timedelta(seconds=60)


class CustomOAuth2Integration(TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
    """Encrypted token store for a Custom REST source's customer-owned OAuth2 client.

    The customer brings their own OAuth2 client (`client_id` / `client_secret` / `token_url`); this row
    is the durable home for the credentials plus the last-minted access token. Unlike the in-memory
    [[OAuth2Auth]] used at request time, the row lets a sync **persist a rotated refresh token** so the
    next sync doesn't fail with `invalid_grant` — required for providers that rotate single-use refresh
    tokens with no grace window (Calendly), where an in-memory-only flow succeeds once and then fails.

    Deliberately product-owned rather than an extension of the core `Integration` model: that model reads
    client credentials from Django settings keyed by a closed `kind` enum and refreshes via a per-kind
    dispatch chain, neither of which can represent a customer-supplied client. Here the credentials live
    on the row and refresh is a single config-driven path through `OAuth2Auth._obtain_token()`.

    `TeamScopedRootMixin` is first in the bases so its fail-closed manager wins the MRO; access outside
    request context (Temporal activities) must go through `objects.for_team(team_id)` or a `team_scope()`
    block — see the locked read in `refresh_and_persist`.
    """

    # db_constraint=False on the FKs to hot tables (posthog_team, posthog_user): creating a real FK
    # constraint takes a SHARE ROW EXCLUSIVE lock on the parent, which stalls under write traffic. Team
    # scoping is enforced at the app level by TeamScopedRootMixin. The external_data_source FK targets a
    # non-hot table, so it keeps its constraint (and its cascade cleans the row up when the source is deleted).
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    external_data_source = models.ForeignKey(
        "warehouse_sources.ExternalDataSource",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="custom_oauth2_integrations",
    )

    # Non-secret OAuth2 config: the exact non-secret OAuth2Auth.__init__ args (client_id, token_url,
    # grant_type, scopes, and the provider-long-tail knobs) plus `refreshed_at` (unix seconds of the
    # last successful mint). Safe to surface to the frontend; never holds a secret.
    config = models.JSONField(default=dict)
    # Secret material, Fernet-encrypted at rest: client_secret, refresh_token (the rotating one),
    # access_token (last-minted token, reused across syncs until expiry like core Integration), and
    # token_expiry (ISO-8601). A DRF serializer over this model MUST omit this field entirely.
    sensitive_config = EncryptedJSONField(default=dict)
    # ERROR_TOKEN_REFRESH_FAILED while a refresh is failing (queryable broken-token state); "" on success.
    errors = models.TextField(blank=True, default="")

    __repr__ = sane_repr("id", "team_id", "external_data_source_id")

    class Meta:
        constraints = [
            # Partial index: only enforce one integration per (team, source) for real source links.
            # A plain UniqueConstraint is a no-op across NULL source FKs (Postgres treats NULLs as
            # distinct), so unlinked rows would slip past it — the condition makes the name hold.
            models.UniqueConstraint(
                fields=["team", "external_data_source"],
                condition=Q(external_data_source__isnull=False),
                name="unique_custom_oauth2_integration_per_source",
            ),
        ]

    def build_auth(self) -> "OAuth2Auth":
        """Construct the request-time auth engine from this row's stored config + secrets."""
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (  # noqa: PLC0415 — keep the HTTP transport stack off the django.setup() model-load path
            OAuth2Auth,
        )

        return OAuth2Auth(
            token_url=self.config.get("token_url"),
            client_id=self.config.get("client_id"),
            client_secret=self.sensitive_config.get("client_secret"),
            grant_type=self.config.get("grant_type", "client_credentials"),
            scopes=self.config.get("scopes"),
            refresh_token=self.sensitive_config.get("refresh_token"),
            access_token_name=self.config.get("access_token_name", "access_token"),
            expires_in_name=self.config.get("expires_in_name", "expires_in"),
            expiry_date_format=self.config.get("expiry_date_format"),
            extra_token_request_params=self.config.get("extra_token_request_params"),
            token_request_headers=self.config.get("token_request_headers"),
            client_auth_method=self.config.get("client_auth_method", "body"),
        )

    @property
    def access_token(self) -> Optional[str]:
        """Last-minted access token, mirroring `Integration.access_token`."""
        return self.sensitive_config.get("access_token")

    def _access_token_expired(self) -> bool:
        expiry = self.sensitive_config.get("token_expiry")
        if not expiry:
            return True
        token_expiry = datetime.fromisoformat(expiry)
        # Refresh proactively at the halfway point of the token's lifetime, mirroring
        # OauthIntegration.access_token_expired (`expires_in / 2`). The engine no longer refreshes
        # mid-sync (integration-backed sources seed a static bearer with manages_own_token=False), so this
        # up-front refresh is the only one — refreshing at the midpoint gives each sync ample runway
        # instead of handing over a token that's seconds from expiry. lifetime is derived from the data
        # we already store: the absolute expiry and the mint timestamp (`refreshed_at`, unix seconds).
        # With no mint timestamp the lifetime is unknown, so fall back to a flat buffer before expiry.
        refreshed_at = self.config.get("refreshed_at")
        if refreshed_at is None:
            return datetime.now(UTC) >= token_expiry - _TOKEN_EXPIRY_BUFFER
        lifetime = token_expiry - datetime.fromtimestamp(refreshed_at, UTC)
        return datetime.now(UTC) >= token_expiry - max(lifetime / 2, timedelta(0))

    def get_access_token(self) -> str:
        """Reuse the stored token while it's valid; refresh + persist only when expired.

        Reusing the cached token until expiry mints only when actually needed, which reduces
        refresh-token rotation churn for high-frequency syncs and caches `client_credentials`
        tokens too.
        """
        token = self.access_token
        if token and not self._access_token_expired():
            return token
        return self.refresh_and_persist()

    def refresh_and_persist(self) -> str:
        """Mint a fresh access token and persist it (plus any rotated refresh token) under a row lock.

        The config-driven twin of `OauthIntegration.refresh_access_token()`: it reads the credentials off
        this row rather than Django settings, mints via the shipped `OAuth2Auth._obtain_token()`, and saves
        the minted access token, its expiry, and a rotated single-use refresh token (when the provider
        returned one) under `select_for_update()` so concurrent syncs can't lose an update. Returns the
        fresh access token. On a token-endpoint failure the row is marked with `ERROR_TOKEN_REFRESH_FAILED`
        and the original error is re-raised.
        """
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (  # noqa: PLC0415 — see build_auth
            OAuth2AuthRequestError,
        )

        # team_scope(): this runs in a Temporal activity, outside the request context the fail-closed
        # manager needs, so the locked read below would raise TeamScopeError without an ambient scope.
        with team_scope(self.team_id):
            try:
                # Mint under the row lock so concurrent syncs serialize: each waits, then re-reads the
                # rotated refresh token before minting its own — a lost update here would orphan a
                # rotating provider on a stale single-use token.
                with transaction.atomic():
                    row = CustomOAuth2Integration.objects.select_for_update().get(pk=self.pk)
                    auth = row.build_auth()
                    auth._obtain_token()
                    row.sensitive_config["access_token"] = auth.token
                    row.sensitive_config["token_expiry"] = auth.token_expiry.isoformat() if auth.token_expiry else None
                    # Rotating providers (e.g. Calendly) return a new single-use refresh token on every
                    # mint; persist it so the next sync doesn't reuse the now-rejected one. Non-rotating
                    # providers leave rotated_refresh_token None, so the stored refresh token is untouched.
                    if auth.rotated_refresh_token:
                        row.sensitive_config["refresh_token"] = auth.rotated_refresh_token
                    row.config["refreshed_at"] = int(time.time())
                    row.errors = ""
                    row.save(update_fields=["sensitive_config", "config", "errors"])
            except OAuth2AuthRequestError:
                # The atomic block above rolled back, so the broken-token state needs its own committed
                # write to survive (and be queryable). A direct queryset UPDATE — not a model save —
                # touches only `errors`, leaving the stored refresh token intact for re-entry to replace.
                CustomOAuth2Integration.objects.filter(pk=self.pk).update(errors=ERROR_TOKEN_REFRESH_FAILED)
                self.errors = ERROR_TOKEN_REFRESH_FAILED
                custom_oauth2_refresh_counter.labels("failed").inc()
                logger.warning("Failed to refresh custom OAuth2 token", integration_id=str(self.pk))
                raise

        custom_oauth2_refresh_counter.labels("success").inc()

        # Keep the in-memory instance the caller holds consistent with what we just persisted.
        self.sensitive_config = row.sensitive_config
        self.config = row.config
        self.errors = row.errors

        # `_obtain_token()` sets the token or raises above; guard so the `str` return type holds.
        if auth.token is None:
            raise OAuth2AuthRequestError("Token endpoint returned no access token")
        return auth.token


def get_custom_oauth2_integration(integration_id: str, team_id: int) -> CustomOAuth2Integration:
    """Load a custom OAuth2 integration for a team, outside request context (Temporal activities).

    Uses `for_team()` — the prescribed fail-closed escape hatch — so a caller can never read another
    team's credentials by id. Raises `CustomOAuth2Integration.DoesNotExist` when the id isn't this team's.
    """
    return CustomOAuth2Integration.objects.for_team(team_id).get(id=integration_id)
