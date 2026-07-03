"""Backend OAuth views for the Slack user-identity link flow.

Two endpoints, both pure-backend (no SPA route). Mirrors the GitHub user-link
convention documented in ``posthog/api/github_callback/README.md``: per-user
OAuth callbacks live under ``/complete/<kind>-link/`` so the
``/integrations/<kind>/callback`` namespace stays reserved for the workspace
install routes the SPA owns.

* ``GET /complete/slack-link/start/``
  Entry point the user lands on from the Slack DM button or settings page.
  Login-gated, so an unauthenticated visitor is bounced through PostHog
  login and returns here with the invite token still in the URL. Validates
  the invite, then redirects to Slack to start the OAuth dance.

* ``GET /complete/slack-link/``
  Slack redirects here after the user authorizes. We exchange the code for a
  user token, call ``users.identity`` to learn the Slack user id + team, and
  upsert a ``UserIntegration(kind="slack")`` row pinning the Slack identity
  to the currently-logged-in PostHog user. On success we DM the user back in
  the original Slack thread (if we have channel + thread context) and bounce
  the browser tab back to Personal integrations with a success query param —
  matching how the GitHub link flow finishes.

The whole feature is gated by ``slack-app-oauth``; with the flag off both
views redirect to the settings page with ``?slack_link_error=flag_off`` so
the user sees a clear toast instead of a 404.
"""

from typing import Any, cast
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.views.decorators.http import require_GET

import structlog

from posthog.api.github_callback.redirects import PERSONAL_INTEGRATIONS_SETTINGS_PATH
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.models.user_integration import user_slack_integration_from_identity
from posthog.views import login_required

from products.slack_app.backend.feature_flags import is_slack_app_oauth_enabled
from products.slack_app.backend.services.slack_user_oauth import (
    CallbackState,
    InviteToken,
    SlackUserOAuthError,
    build_authorize_url,
    exchange_code,
)

logger = structlog.get_logger(__name__)

# `PERSONAL_INTEGRATIONS_SETTINGS_PATH` is imported from the github_callback
# module so a future rename of the settings URL updates both providers'
# redirect targets in one move; the query-param convention
# (`<kind>_link_success=1` / `<kind>_link_error=<reason>`) is shared too.


def _callback_redirect_uri() -> str:
    base = settings.SITE_URL.rstrip("/")
    return f"{base}/complete/slack-link/"


def _settings_redirect(*, error: str | None = None) -> HttpResponseRedirect:
    """Bounce back to Personal integrations with a result query param.

    Success and error paths share the same destination; the difference is
    only the query param the frontend's ``afterMount`` reads to fire the
    success or error toast.
    """
    param = {"slack_link_error": error} if error else {"slack_link_success": "1"}
    return redirect(f"{PERSONAL_INTEGRATIONS_SETTINGS_PATH}?{urlencode(param)}")


def _load_workspace_integration(posthog_team_id: int, slack_team_id: str) -> Integration | None:
    return (
        Integration.objects.filter(team_id=posthog_team_id, kind="slack", integration_id=slack_team_id)
        .select_related("team", "team__organization")
        .first()
    )


@require_GET
@login_required
def slack_user_link_authorize(request: HttpRequest) -> HttpResponse:
    """Validate the invite, then redirect to Slack OAuth.

    The user is necessarily authenticated by the time this runs (the
    ``login_required`` decorator handles the bounce). Bad / expired invites
    bounce back to the settings page with an error param instead of
    rendering a dead-end HTML page — the toast handler in
    ``personalIntegrationsLogic`` explains what went wrong in context.
    """
    invite = InviteToken.decode(request.GET.get("state", ""))
    if invite is None:
        return _settings_redirect(error="invalid_state")

    workspace_integration = _load_workspace_integration(invite.posthog_team_id, invite.slack_team_id)
    if workspace_integration is None:
        return _settings_redirect(error="workspace_not_found")

    if not is_slack_app_oauth_enabled(workspace_integration, invite.slack_team_id):
        return _settings_redirect(error="flag_off")

    callback_state = CallbackState(
        slack_team_id=invite.slack_team_id,
        posthog_team_id=invite.posthog_team_id,
        posthog_user_id=request.user.id,
        slack_user_id=invite.slack_user_id,
        channel=invite.channel,
        thread_ts=invite.thread_ts,
    ).encode()

    try:
        authorize_url = build_authorize_url(redirect_uri=_callback_redirect_uri(), state=callback_state)
    except SlackUserOAuthError:
        logger.exception("slack_app_user_link_authorize_misconfigured")
        return _settings_redirect(error="not_configured")

    return HttpResponseRedirect(authorize_url)


@require_GET
@login_required
def slack_user_link_callback(request: HttpRequest) -> HttpResponse:
    """Receive Slack's redirect, exchange the code, persist the link, and
    bounce back to Personal integrations.

    Re-checks login + feature flag at this end so a stale tab can't bypass
    either guard. The session-mismatch check below binds the callback to the
    PostHog user who started the flow (``state.posthog_user_id``) — without
    it, a leaked invite URL + Slack ``code`` (15-min lifetime) opened in a
    different user's browser would write the attacker's Slack identity to
    the victim's PostHog account.
    """
    slack_error = request.GET.get("error")
    if slack_error:
        # Pass Slack's error code straight through — the frontend toast
        # handler renders known codes (`access_denied`, …) with friendly
        # copy and falls back to a generic message for anything else.
        return _settings_redirect(error=slack_error)

    code = request.GET.get("code", "")
    state = CallbackState.decode(request.GET.get("state", ""))
    if not code or state is None:
        return _settings_redirect(error="invalid_state")

    workspace_integration = _load_workspace_integration(state.posthog_team_id, state.slack_team_id)
    if workspace_integration is None:
        return _settings_redirect(error="workspace_not_found")
    if not is_slack_app_oauth_enabled(workspace_integration, state.slack_team_id):
        return _settings_redirect(error="flag_off")

    try:
        identity = exchange_code(code=code, redirect_uri=_callback_redirect_uri())
    except SlackUserOAuthError as exc:
        logger.warning("slack_app_user_link_callback_exchange_failed", error=str(exc))
        return _settings_redirect(error="exchange_failed")

    # Hard-bind to the workspace from the original invite: if the user
    # authorized in a different Slack workspace tab, refuse rather than
    # silently linking them to the wrong workspace.
    if identity.slack_team_id != state.slack_team_id:
        logger.warning(
            "slack_app_user_link_callback_team_mismatch",
            expected=state.slack_team_id,
            actual=identity.slack_team_id,
        )
        return _settings_redirect(error="team_mismatch")

    # `state.slack_user_id` is informational — if the user clicks an invite
    # meant for a different person but authorizes as themselves, that's fine
    # (they're linking their own identity). We log the divergence so support
    # can spot a forwarded-button case.
    if state.slack_user_id is not None and identity.slack_user_id != state.slack_user_id:
        logger.info(
            "slack_app_user_link_callback_user_diverged_from_invite",
            invite_user=state.slack_user_id,
            authed_user=identity.slack_user_id,
        )

    # `request.user` is `User | AnonymousUser` to mypy even though
    # `@login_required` rules out the anonymous case at runtime; cast so the
    # factory's `user: User` signature is satisfied without an `assert`.
    posthog_user = cast(User, request.user)

    # CSRF guard: bind the link write to the same PostHog user who initiated
    # the flow. Without this, an attacker who completes their own OAuth dance
    # could send the resulting `?code=…&state=…` URL to a victim and have the
    # victim's browser write the *attacker's* Slack identity into the *victim's*
    # PostHog account — every subsequent @mention from the attacker would then
    # resolve as the victim. `org_mismatch` below catches cross-org cases but
    # not the same-org colleague case, so this check is the actual boundary.
    if state.posthog_user_id != posthog_user.id:
        logger.warning(
            "slack_app_user_link_callback_session_mismatch",
            state_posthog_user_id=state.posthog_user_id,
            request_posthog_user_id=posthog_user.id,
        )
        return _settings_redirect(error="session_mismatch")

    # Refuse to write a link row for a PostHog user who isn't a member of
    # the workspace's org. The org-scope filter in `find_linked_posthog_user`
    # would already skip such rows at resolve time, but writing them anyway
    # would let anyone who got hold of a signed invite URL (forwarded DM,
    # screenshot, etc.) seed orphan rows on the workspace.
    if not OrganizationMembership.objects.filter(
        user_id=posthog_user.id,
        organization_id=workspace_integration.team.organization_id,
    ).exists():
        logger.warning(
            "slack_app_user_link_callback_org_mismatch",
            posthog_user_id=posthog_user.id,
            posthog_team_id=workspace_integration.team_id,
            organization_id=workspace_integration.team.organization_id,
        )
        return _settings_redirect(error="org_mismatch")

    user_slack_integration_from_identity(
        posthog_user,
        slack_user_id=identity.slack_user_id,
        slack_team_id=identity.slack_team_id,
        slack_team_name=identity.slack_team_name,
        slack_email_at_link=identity.slack_email,
        user_access_token=identity.user_access_token,
        user_refresh_token=identity.user_refresh_token,
    )

    _post_link_success_followup(
        workspace_integration=workspace_integration,
        slack_user_id=identity.slack_user_id,
        channel=state.channel,
        thread_ts=state.thread_ts,
    )

    return _settings_redirect()


def _post_link_success_followup(
    *,
    workspace_integration: Integration,
    slack_user_id: str,
    channel: Any,
    thread_ts: Any,
) -> None:
    """Best-effort follow-up DM/thread message confirming the link. The user
    has already been bounced back to the settings page in their browser, so
    a Slack post failure is not surfaced — it's a nice-to-have for context,
    not a correctness requirement.
    """
    if not isinstance(channel, str) or not channel:
        return
    try:
        client = SlackIntegration(workspace_integration).client
        client.chat_postEphemeral(
            channel=channel,
            user=slack_user_id,
            thread_ts=thread_ts if isinstance(thread_ts, str) else None,
            text="✅ Your PostHog account is now linked. Mention me again and I'll route to you correctly.",
        )
    except Exception:
        logger.info(
            "slack_app_user_link_success_followup_failed",
            channel=channel,
            slack_user_id=slack_user_id,
            exc_info=True,
        )
