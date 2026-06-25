"""Slack user-identity OAuth + linked-user resolution.

Single home for the whole user-link feature surface:

* Feature flag check + linked-user lookup, used by inbound event resolvers
  (``resolve_slack_user`` etc.) before falling back to email matching.
* Signed-state Pydantic models (``InviteToken``, ``CallbackState``) that
  flow through Slack's OAuth redirects.
* The Sign-in-with-Slack OAuth dance: authorize URL builder, code exchange,
  ``users.identity`` call, kept thin and pure so the view layer can compose
  it with login state / templates / follow-up messages.
* Block Kit invite-message poster the resolver uses when email matching
  fails and the user has a recovery affordance to offer.

Distinct from the workspace install flow in
``posthog.models.integration.OauthIntegration``: that one mints workspace-
level bot tokens and persists them as an ``Integration`` row. This one runs
the user-token flow (``user_scope=identity.basic,identity.email``) and
stores the resulting credential on a ``UserIntegration(kind="slack")`` row
in symmetry with the GitHub personal integration.
"""

from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from django.conf import settings
from django.core import signing

import requests
import structlog
from pydantic import BaseModel, ValidationError
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from posthog.models.instance_setting import get_instance_settings
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

logger = structlog.get_logger(__name__)


def find_linked_posthog_user(
    *,
    slack_user_id: str,
    slack_team_id: str,
    candidate_org_ids: set[UUID],
) -> User | None:
    """Return the PostHog ``User`` linked to this Slack identity, scoped to the
    organizations connected to this workspace.

    Multiple PostHog users may legitimately link to the same Slack identity
    (e.g. one Slack account → personal + work PostHog accounts). When more
    than one matching row passes the org-scope check, we return the
    **most-recently-linked** one — they just authenticated, presumably with
    intent — and emit a warn-log so the rare collision is visible in prod.

    Returns ``None`` when no link exists or none of the linked users are
    members of a connected org. Caller still owns the access-level
    (``effective_membership_level``) check on the resolved user.
    """
    if not slack_user_id or not slack_team_id or not candidate_org_ids:
        return None
    # Split the lookup into two queries — the JSON match on `UserIntegration`
    # followed by an org-membership check — instead of a single cross-table
    # join. The chained `user__organization_memberships__organization_id__in`
    # lookup gets rejected by Django when one of the joined models lives on
    # a different database (which `User` does in PostHog's deployment), so a
    # straight-line equivalent keeps the query portable across routers.
    try:
        links = list(
            UserIntegration.objects.filter(
                kind=UserIntegration.IntegrationKind.SLACK,
                integration_id=slack_user_id,
                config__slack_team_id=slack_team_id,
            )
            .select_related("user")
            .order_by("-created_at")
        )
        if not links:
            return None
        # Org-scope filter as a set lookup so we keep the per-row iteration
        # below in stable most-recent-first order without a second per-row query.
        user_ids = [link.user_id for link in links if link.user is not None]
        accessible_user_ids = set(
            OrganizationMembership.objects.filter(
                user_id__in=user_ids, organization_id__in=candidate_org_ids
            ).values_list("user_id", flat=True)
        )
        if not accessible_user_ids:
            return None
        if len(links) > 1:
            # Telemetry for the multi-link ambiguity case. Picking
            # most-recent is deliberate but it's worth seeing how often
            # this fires — if it's common, the linking flow needs harder
            # guard rails (or a DB-level partial unique constraint).
            logger.warning(
                "slack_app_user_link_multiple_matches",
                slack_user_id=slack_user_id,
                slack_team_id=slack_team_id,
                link_count=len(links),
                accessible_count=len(accessible_user_ids),
            )
        for link in links:
            if link.user_id in accessible_user_ids:
                return link.user
        return None
    except Exception:
        logger.warning(
            "slack_app_user_link_lookup_failed",
            slack_user_id=slack_user_id,
            slack_team_id=slack_team_id,
            exc_info=True,
        )
        return None


# ---------------------------------------------------------------------------
# Signed-state Pydantic models
# ---------------------------------------------------------------------------

# Short-lived invite tokens carry the Slack-side context (user id, workspace,
# thread) to the PostHog authorize view; longer would let the same Slack DM
# be replayed by anyone who scrapes it from a forwarded message.
INVITE_TOKEN_SALT = "slack_user_link_invite"
INVITE_TOKEN_MAX_AGE_SECONDS = 15 * 60

# Distinct salt from the invite token: an invite leaked from a Slack DM must
# not be replayable as a callback state.
CALLBACK_STATE_SALT = "slack_user_link_oauth"
CALLBACK_STATE_MAX_AGE_SECONDS = 15 * 60


class InviteToken(BaseModel):
    """Slack-side invite payload signed into the URL on the "Link my PostHog
    account" button. Decoded by the authorize view to learn which workspace
    to link against and how to get the user back to the right Slack thread
    after the OAuth dance.

    ``slack_user_id`` is only present on Slack-DM-initiated invites (we knew
    who triggered the matching failure). Settings-initiated invites omit it
    because the user hasn't authenticated to Slack yet — we'll learn their
    identity only from the OAuth callback.
    """

    slack_team_id: str
    posthog_team_id: int
    slack_user_id: str | None = None
    channel: str | None = None
    thread_ts: str | None = None

    def encode(self) -> str:
        return signing.dumps(self.model_dump(exclude_none=True), salt=INVITE_TOKEN_SALT, compress=True)

    @classmethod
    def decode(cls, token: str) -> "InviteToken | None":
        """Return ``None`` on bad signature, expiry, or schema mismatch so
        callers can render a friendly error instead of throwing."""
        try:
            payload = signing.loads(token, salt=INVITE_TOKEN_SALT, max_age=INVITE_TOKEN_MAX_AGE_SECONDS)
        except (signing.BadSignature, signing.SignatureExpired):
            return None
        if not isinstance(payload, dict):
            return None
        try:
            return cls.model_validate(payload)
        except ValidationError:
            return None


class CallbackState(BaseModel):
    """State we round-trip through Slack's authorize endpoint. Carries the
    invite context plus the PostHog user who started the flow, so the
    callback can attribute the link to the right account even if the user
    swaps browsers mid-flow.
    """

    slack_team_id: str
    posthog_team_id: int
    posthog_user_id: int
    slack_user_id: str | None = None
    channel: str | None = None
    thread_ts: str | None = None

    def encode(self) -> str:
        return signing.dumps(self.model_dump(exclude_none=True), salt=CALLBACK_STATE_SALT, compress=True)

    @classmethod
    def decode(cls, token: str) -> "CallbackState | None":
        try:
            payload = signing.loads(token, salt=CALLBACK_STATE_SALT, max_age=CALLBACK_STATE_MAX_AGE_SECONDS)
        except (signing.BadSignature, signing.SignatureExpired):
            return None
        if not isinstance(payload, dict):
            return None
        try:
            return cls.model_validate(payload)
        except ValidationError:
            return None


def build_invite_url(
    *,
    slack_user_id: str | None,
    slack_team_id: str,
    posthog_team_id: int,
    channel: str | None,
    thread_ts: str | None,
) -> str:
    """Full https URL the Slack button opens. Routes through PostHog's
    ``SITE_URL`` so a workspace in a region different from the one that
    received the event still lands on the right instance after the proxy.
    """
    token = InviteToken(
        slack_team_id=slack_team_id,
        posthog_team_id=posthog_team_id,
        slack_user_id=slack_user_id,
        channel=channel,
        thread_ts=thread_ts,
    ).encode()
    base = settings.SITE_URL.rstrip("/")
    return f"{base}/complete/slack-link/start/?{urlencode({'state': token})}"


# ---------------------------------------------------------------------------
# Sign-in-with-Slack OAuth flow
# ---------------------------------------------------------------------------

SLACK_AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
SLACK_TOKEN_URL = "https://slack.com/api/oauth.v2.access"

# `identity.basic` returns `{user: {id, name}, team: {id}}` — the bare
# minimum we need to bind a Slack user to a PostHog user. `identity.email`
# powers the support diagnostics field stored alongside the link. The user
# token issued for these scopes is persisted on the UserIntegration row in
# symmetry with the GitHub personal flow.
USER_IDENTITY_SCOPES = "identity.basic,identity.email"


class SlackUserOAuthError(Exception):
    """Raised when the OAuth exchange or identity fetch fails. The view
    catches this and redirects back to settings with an error param."""


class SlackIdentity(BaseModel):
    """Result of ``oauth.v2.access`` + ``users.identity`` for the user flow.

    ``user_refresh_token`` is only populated when the Slack app has
    ``token_rotation_enabled``; with rotation off (today) Slack omits the
    field from the OAuth response. Capturing it defensively means the
    callback shape doesn't change the day rotation gets flipped on.
    """

    slack_user_id: str
    slack_team_id: str
    slack_team_name: str | None = None
    slack_email: str | None = None
    user_access_token: str
    user_refresh_token: str | None = None


def _credentials() -> tuple[str, str]:
    """Resolve Slack app credentials at call time so dev/test overrides via
    instance settings work the same way the workspace install flow does.
    """
    from_settings = get_instance_settings(["SLACK_APP_CLIENT_ID", "SLACK_APP_CLIENT_SECRET"])
    client_id = from_settings.get("SLACK_APP_CLIENT_ID") or ""
    client_secret = from_settings.get("SLACK_APP_CLIENT_SECRET") or ""
    if not client_id or not client_secret:
        raise SlackUserOAuthError("Slack app credentials not configured")
    return client_id, client_secret


def build_authorize_url(*, redirect_uri: str, state: str) -> str:
    """The full Slack URL the user is redirected to. ``user_scope`` is the
    Sign-in-with-Slack lever — bot scopes stay empty so the user doesn't see
    a permissions prompt for things the bot already has.
    """
    client_id, _ = _credentials()
    params = {
        "client_id": client_id,
        "user_scope": USER_IDENTITY_SCOPES,
        "scope": "",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{SLACK_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code(*, code: str, redirect_uri: str) -> SlackIdentity:
    """Trade the auth code for a user token, then call ``users.identity`` to
    learn who that token belongs to. The token is returned on ``SlackIdentity``
    so the caller can persist it alongside the link.

    ``redirect_uri`` must match the one used on ``build_authorize_url``
    exactly; Slack rejects the exchange otherwise.
    """
    client_id, client_secret = _credentials()
    try:
        response = requests.post(
            SLACK_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        raise SlackUserOAuthError("Slack OAuth request failed") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise SlackUserOAuthError("Slack OAuth returned non-JSON response") from exc

    if not payload.get("ok"):
        logger.warning("slack_app_user_link_oauth_exchange_failed", error=payload.get("error"))
        raise SlackUserOAuthError(f"Slack OAuth exchange failed: {payload.get('error')}")

    authed_user = payload.get("authed_user") or {}
    user_token = authed_user.get("access_token")
    if not user_token:
        raise SlackUserOAuthError("Slack OAuth response missing authed_user.access_token")

    # `authed_user.id` and `team.id` from `oauth.v2.access` are authoritative,
    # but we still call `users.identity` to pick up the email + team name in
    # the same request the user already authorized. Slack returns these
    # under the user-token scope, not the bot token, so we have to use the
    # token we just received.
    try:
        identity_response = WebClient(token=user_token).users_identity()
    except SlackApiError as exc:
        error = exc.response.get("error") if exc.response else None
        logger.warning("slack_app_user_link_users_identity_failed", error=error)
        raise SlackUserOAuthError(f"Slack users.identity failed: {error}") from exc

    user_info = identity_response.get("user") or {}
    team_info = identity_response.get("team") or {}
    slack_user_id = user_info.get("id") or authed_user.get("id")
    slack_team_id = team_info.get("id") or (payload.get("team") or {}).get("id")
    if not slack_user_id or not slack_team_id:
        raise SlackUserOAuthError("Slack identity response missing user.id or team.id")

    return SlackIdentity(
        slack_user_id=slack_user_id,
        slack_team_id=slack_team_id,
        slack_team_name=team_info.get("name") or (payload.get("team") or {}).get("name"),
        slack_email=user_info.get("email"),
        user_access_token=user_token,
        # `refresh_token` is only present when the Slack app has
        # `token_rotation_enabled`; falls back to None in today's manifest.
        user_refresh_token=authed_user.get("refresh_token"),
    )


# ---------------------------------------------------------------------------
# Slack-side invite message
# ---------------------------------------------------------------------------


def post_link_invite_message(
    *,
    slack_client: WebClient,
    channel: str,
    slack_user_id: str,
    thread_ts: str | None,
    slack_email: str | None,
    invite_url: str,
) -> None:
    """Post an ephemeral Block Kit message inviting the user to link their
    PostHog account. Visible only to ``slack_user_id``.

    The wording is intentionally minimal — a separate public thread reply
    already diagnoses the matching failure for the rest of the channel, and
    this message's only job is to surface the one-click recovery affordance
    to the affected user. Repeating the diagnosis here would just clutter
    their view.

    Slack's ``url``-bearing buttons require no interactivity handler — clicks
    open the link in the user's browser and the OAuth dance proceeds without
    another round-trip to PostHog. Failures here are logged and swallowed:
    the public text reply has already informed the channel about the
    matching failure, so a button-post failure must not double-up a second
    visible error.
    """
    # `slack_email` is intentionally not interpolated into the body — the
    # public thread reply already names the address PostHog tried to match.
    del slack_email
    fallback_text = "Link your PostHog account to fix this for future mentions."
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"👉 {fallback_text}",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Link my PostHog account"},
                    "style": "primary",
                    "url": invite_url,
                }
            ],
        },
    ]
    try:
        slack_client.chat_postEphemeral(
            channel=channel,
            user=slack_user_id,
            thread_ts=thread_ts,
            text=fallback_text,
            blocks=blocks,
        )
    except Exception:
        logger.warning(
            "slack_app_user_link_invite_post_failed",
            channel=channel,
            slack_user_id=slack_user_id,
            exc_info=True,
        )
