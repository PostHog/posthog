"""WhatsApp identity linking and chat binding.

WhatsApp has no user OAuth: linking rides the shared one-shot cache codes. The
login-gated view redirects to a ``wa.me`` deep link whose prefilled text is
``link <code>``; the user sends it in the DM, and redemption links the sender's
``wa_id`` (their phone number) to the minter's PostHog account and binds the DM
chat to the team.

The v1 surface is DMs only (the Cloud API has no user-created groups), so the chat
IS the user: one ``Integration`` row per ``wa_id``, bound to exactly one team.
Whoever sends the code is trusted to be the minter — the same trust model as the
Telegram ``/start`` flow, bounded by one-shot redemption and the 15-minute TTL.
"""

import re
import time
from uuid import UUID

from django.conf import settings

import structlog

from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

from products.slack_app.backend.services.chat_link_codes import mint_link_code, redeem_link_code
from products.slack_app.backend.services.slack_user_oauth import _pick_accessible_linked_user

logger = structlog.get_logger(__name__)

_LINK_COMMAND_RE = re.compile(r"^link(?:\s+(\S+))?\s*$", re.IGNORECASE)


def mint_whatsapp_link_code(*, posthog_user_id: int, team_id: int) -> str:
    return mint_link_code(provider="whatsapp", purpose="link", posthog_user_id=posthog_user_id, team_id=team_id)


def link_command_code(text: str) -> str | None:
    """The code carried by a ``link <code>`` message.

    Returns ``None`` when the text isn't a link command, and ``""`` for the bare form.
    """
    match = _LINK_COMMAND_RE.match(text.strip())
    if match is None:
        return None
    return match.group(1) or ""


def user_whatsapp_integration_from_identity(user: User, *, wa_id: str, profile_name: str | None) -> UserIntegration:
    """Create or refresh the WhatsApp identity link.

    Symmetric with the Telegram personal integration: WhatsApp issues no user
    token — the central business number is the only credential.
    """
    integration, _created = UserIntegration.objects.update_or_create(
        user=user,
        kind=UserIntegration.IntegrationKind.WHATSAPP,
        integration_id=wa_id,
        defaults={
            "config": {
                "profile_name": profile_name,
                "linked_at": int(time.time()),
            },
        },
    )
    return integration


def find_linked_whatsapp_user(*, wa_id: str, candidate_org_ids: set[UUID]) -> User | None:
    """The PostHog user linked to this WhatsApp identity, scoped to the candidate orgs.

    No workspace filter: the bot is central and ``wa_id`` (the phone number) is
    global, so one link row serves every conversation.
    """
    if not wa_id or not candidate_org_ids:
        return None
    try:
        links = list(
            UserIntegration.objects.filter(
                kind=UserIntegration.IntegrationKind.WHATSAPP,
                integration_id=wa_id,
            )
            .select_related("user")
            .order_by("-created_at")
        )
        return _pick_accessible_linked_user(
            links,
            candidate_org_ids,
            warn_log_fields={"wa_id": wa_id},
        )
    except Exception:
        logger.warning("slack_app_whatsapp_user_link_lookup_failed", wa_id=wa_id, exc_info=True)
        return None


def bind_chat_to_team(*, team: Team, wa_id: str, profile_name: str | None, bound_by_user_id: int) -> Integration | None:
    """Bind a WhatsApp DM (one ``wa_id``) to a team via an Integration row.

    Returns ``None`` when the chat is already bound to a different team — a chat
    belongs to exactly one project, and silently rebinding would let a second org
    steal an already-connected chat.
    """
    if not wa_id:
        return None
    if Integration.objects.filter(kind="whatsapp", integration_id=wa_id).exclude(team_id=team.id).exists():
        return None
    integration, _created = Integration.objects.update_or_create(
        team=team,
        kind="whatsapp",
        integration_id=wa_id,
        defaults={
            "config": {
                "profile_name": profile_name,
                "bound_by_user_id": bound_by_user_id,
                "linked_at": int(time.time()),
            }
        },
    )
    return integration


def handle_link_redemption(*, wa_id: str, profile_name: str | None, text: str) -> str:
    """Redeem a ``link <code>`` DM; returns the reply text."""
    code = link_command_code(text)
    link_url = f"{settings.SITE_URL}/whatsapp/link/start/"

    if not code:
        return (
            "Hi! I'm the PostHog bot. To get started, link your PostHog account: "
            f"open {link_url}?team_id=<your project id> while logged in to PostHog."
        )

    payload = redeem_link_code("whatsapp", code, expected_purpose="link")
    if payload is None:
        return f"That link has expired or was already used. Start again from {link_url}?team_id=<your project id>."

    team = Team.objects.filter(id=payload.team_id).select_related("organization").first()
    user = User.objects.filter(id=payload.posthog_user_id).first()
    if team is None or user is None:
        return "Something's off with that link — the project or account behind it no longer exists."

    if not OrganizationMembership.objects.filter(user_id=user.id, organization_id=team.organization_id).exists():
        logger.warning(
            "slack_app_whatsapp_link_org_mismatch",
            posthog_user_id=user.id,
            team_id=team.id,
            wa_id=wa_id,
        )
        return "The account behind that link isn't a member of the project's organization anymore."

    user_whatsapp_integration_from_identity(user, wa_id=wa_id, profile_name=profile_name)
    logger.info(
        "slack_app_whatsapp_identity_linked",
        posthog_user_id=user.id,
        wa_id=wa_id,
        team_id=team.id,
    )

    bound = bind_chat_to_team(team=team, wa_id=wa_id, profile_name=profile_name, bound_by_user_id=user.id)
    if bound is None:
        return (
            "Your account is linked, but this chat is already connected to another PostHog project, "
            "so I left that connection alone."
        )
    return f"You're all set — your account is linked and this chat is connected to {team.name}. Send me a task to get started."
