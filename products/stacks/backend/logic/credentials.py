"""Short-lived API credentials for the engine, minted for the person or CI job that admitted a run.

The engine calls PostHog's public API as that caller. Each run gets its own OAuth access token, for the
run's exact target project and for exactly the scopes checked at admission. The token value exists only in
the worker's memory. The worker revokes it when the run ends, and a takeover revokes it by its row id.

The tokens come from one first-party OAuth application, which the write lock exempts. Like the sandbox
applications in `posthog/temporal/oauth.py`, the row is provisioned per region out of band
(`manage.py provision_stacks_oauth_app`), and every mint checks the row's identity first.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

import structlog

from posthog.models.oauth import OAuthAccessToken, OAuthApplication, mint_oauth_access_token
from posthog.models.user import User

from ..engine_adapter import EngineCredentials
from .kinds import scope_ceiling

logger = structlog.get_logger(__name__)

STACKS_OAUTH_CLIENT_ID = "posthog-stacks-first-party"
STACKS_OAUTH_APP_NAME = "PostHog stacks"
STACKS_OAUTH_REDIRECT_URI = "https://localhost"
# Longer than the push activity's timeout, so a token cannot expire mid-run, and short enough that a token a
# crashed worker failed to revoke stops working soon after.
CREDENTIAL_LIFETIME = timedelta(minutes=45)


class CallerUnavailable(Exception):
    pass


def _app_defaults() -> dict:
    return {
        "name": STACKS_OAUTH_APP_NAME,
        "client_secret": secrets.token_urlsafe(48),
        "client_type": "confidential",
        "authorization_grant_type": "authorization-code",
        "redirect_uris": STACKS_OAUTH_REDIRECT_URI,
        "algorithm": "RS256",
        "is_first_party": True,
        "scopes": scope_ceiling(),
    }


def provision_stacks_oauth_app() -> OAuthApplication:
    """Create or update the application row. Safe to run again, and when two processes run it at once."""
    try:
        with transaction.atomic():
            app, created = OAuthApplication.objects.get_or_create(
                client_id=STACKS_OAUTH_CLIENT_ID, defaults=_app_defaults()
            )
    except (IntegrityError, ValidationError):
        # `save()` validates before it inserts, so a concurrent first insert can surface as either error.
        app, created = OAuthApplication.objects.get(client_id=STACKS_OAUTH_CLIENT_ID), False
    # A row that is not the one provisioning makes is refused before anything on it changes.
    _check_identity(app, check_scopes=False)
    if not created and app.scopes != scope_ceiling():
        app.scopes = scope_ceiling()
        app.save(update_fields=["scopes"])
    _check_identity(app)
    return app


def _check_identity(app: OAuthApplication, *, check_scopes: bool = True) -> None:
    # The write lock exempts this application's live push tokens, so a row that is not exactly the one
    # provisioning creates must never mint one.
    if (
        app.client_id != STACKS_OAUTH_CLIENT_ID
        or not app.is_first_party
        or app.is_dcr_client
        or app.client_type != "confidential"
        or app.authorization_grant_type != "authorization-code"
        or app.redirect_uris.strip() != STACKS_OAUTH_REDIRECT_URI
        or (check_scopes and not app.scopes)
    ):
        raise CallerUnavailable("PostHog's stack application is not set up correctly. Contact support.")


def stacks_oauth_app() -> OAuthApplication:
    app = OAuthApplication.objects.filter(client_id=STACKS_OAUTH_CLIENT_ID).first()
    if app is None:
        if not (settings.DEBUG or settings.TEST):
            raise CallerUnavailable("PostHog's stack application is not set up. Contact support.")
        app = provision_stacks_oauth_app()
    _check_identity(app)
    return app


def api_host() -> str:
    return (settings.STACKS_ENGINE_API_HOST or settings.SITE_URL).rstrip("/")


def mint(
    *,
    user: User,
    target_team_id: int,
    scopes: list[str],
    secret_values: dict[str, str] | None = None,
    expires_at: datetime | None = None,
) -> tuple[OAuthAccessToken, EngineCredentials]:
    """A token for one run, limited to its target project, to the scopes checked at admission, and to the
    lifetime the admitting credential has left."""
    app = stacks_oauth_app()
    if not scopes or not set(scopes) <= set(app.scopes):
        raise CallerUnavailable("This run needs a scope PostHog's stack application cannot grant. Contact support.")
    lifetime = CREDENTIAL_LIFETIME
    if expires_at is not None:
        # A second short, so the token is gone before the credential is, whatever the clock read in between.
        lifetime = min(lifetime, expires_at - timezone.now() - timedelta(seconds=1))
        if lifetime <= timedelta(0):
            raise CallerUnavailable("The key or token that asked for this run expired. Run it again with a valid one.")
    token = mint_oauth_access_token(
        application=app,
        user=user,
        scope=" ".join(sorted(scopes)),
        lifetime=lifetime,
        scoped_teams=[target_team_id],
    )
    credentials = EngineCredentials(
        host=api_host(), project_id=target_team_id, api_key=token.token, secrets=secret_values or {}
    )
    return token, credentials


def revoke(token_id: UUID | None) -> bool:
    """Delete a run's token. False when the delete failed, which is logged and never raised."""
    if token_id is None:
        return True
    try:
        OAuthAccessToken.objects.filter(id=token_id).delete()
    except Exception:
        logger.exception("stacks_token_revoke_failed", token_id=token_id)
        return False
    return True
