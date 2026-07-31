"""Login-gated entry point for WhatsApp identity linking.

Mints a one-shot code for the logged-in user and redirects to a ``wa.me`` deep link
whose prefilled text is ``link <code>`` — the user just hits send in WhatsApp, and
the webhook redeems the code. DM-only surface, so there is no group-connect flow.
"""

from typing import cast
from urllib.parse import quote

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.views.decorators.http import require_GET

import structlog

from posthog.models.user import User
from posthog.views import login_required

from products.slack_app.backend.services.whatsapp_api import WhatsAppApiError, get_bot_phone_number
from products.slack_app.backend.services.whatsapp_link import mint_whatsapp_link_code
from products.slack_app.backend.views.telegram_link import _resolve_team_for_member

logger = structlog.get_logger(__name__)


@require_GET
@login_required
def whatsapp_link_start(request: HttpRequest) -> HttpResponse:
    team = _resolve_team_for_member(request)
    if isinstance(team, HttpResponse):
        return team
    try:
        bot_number = get_bot_phone_number()
    except WhatsAppApiError:
        return HttpResponse("WhatsApp isn't configured on this PostHog instance.", status=503)
    code = mint_whatsapp_link_code(posthog_user_id=cast(User, request.user).id, team_id=team.id)
    return HttpResponseRedirect(f"https://wa.me/{bot_number}?text={quote(f'link {code}')}")
