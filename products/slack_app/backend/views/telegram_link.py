"""Login-gated entry points for Telegram identity linking and group binding.

Telegram has no OAuth dance: these views mint a one-shot code for the logged-in
user and hand it to Telegram — as a ``t.me`` deep link for DMs (``/start <code>``)
or as a command to paste into a group (``/connect <code>``). Redemption happens in
the webhook when the bot receives the command.
"""

from typing import cast

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.utils.html import escape
from django.views.decorators.http import require_GET

import structlog

from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.views import login_required

from products.slack_app.backend.services.telegram_api import TelegramApiError, get_bot_identity
from products.slack_app.backend.services.telegram_link import LINK_CODE_TTL_SECONDS, mint_link_code

logger = structlog.get_logger(__name__)


def _resolve_team_for_member(request: HttpRequest) -> Team | HttpResponse:
    try:
        team_id = int(request.GET.get("team_id", ""))
    except ValueError:
        return HttpResponse("Missing or invalid team_id.", status=400)
    team = Team.objects.filter(id=team_id).select_related("organization").first()
    posthog_user = cast(User, request.user)
    if (
        team is None
        or not OrganizationMembership.objects.filter(
            user_id=posthog_user.id, organization_id=team.organization_id
        ).exists()
    ):
        # One answer for "no such team" and "not your team": don't leak which
        # team ids exist to logged-in users of other orgs.
        return HttpResponse("Project not found.", status=404)
    return team


@require_GET
@login_required
def telegram_link_start(request: HttpRequest) -> HttpResponse:
    team = _resolve_team_for_member(request)
    if isinstance(team, HttpResponse):
        return team
    try:
        bot_username = get_bot_identity().get("username")
    except TelegramApiError:
        return HttpResponse("Telegram isn't configured on this PostHog instance.", status=503)
    code = mint_link_code(purpose="link", posthog_user_id=cast(User, request.user).id, team_id=team.id)
    return HttpResponseRedirect(f"https://t.me/{bot_username}?start={code}")


@require_GET
@login_required
def telegram_connect_start(request: HttpRequest) -> HttpResponse:
    team = _resolve_team_for_member(request)
    if isinstance(team, HttpResponse):
        return team
    try:
        get_bot_identity()
    except TelegramApiError:
        return HttpResponse("Telegram isn't configured on this PostHog instance.", status=503)
    code = mint_link_code(purpose="connect", posthog_user_id=cast(User, request.user).id, team_id=team.id)
    minutes = LINK_CODE_TTL_SECONDS // 60
    return HttpResponse(
        "<html><body>"
        f"<p>Paste this in your Telegram group within {minutes} minutes:</p>"
        f"<p><code>/connect {escape(code)}</code></p>"
        f"<p>This connects the group to <strong>{escape(team.name)}</strong>. "
        "Make sure you've linked your own account first (DM the bot via the link flow).</p>"
        "</body></html>"
    )
