"""Telegram identity linking and chat binding.

Telegram has no OAuth: the "callback" is the bot receiving a command that carries a
code we minted for a logged-in PostHog user. The deep-link payload is capped at 64
URL-safe characters, so instead of a signed token the link carries a random one-shot
handle whose context (who minted it, for which team, for which purpose) lives
server-side in the cache.

Two distinct purposes, never interchangeable:

* ``link`` — redeemed via ``/start <code>`` in a DM. Links the sender's Telegram
  identity to the minter's PostHog account and binds the DM chat to the team.
  Whoever pastes the code is trusted to be the minter (same trust model as the
  Slack invite token); the one-shot redemption and 15-minute TTL bound the leak
  window, and the redeeming Telegram id is logged for audit.
* ``connect`` — redeemed via ``/connect <code>`` in a group. The command is visible
  to the whole group, so the code alone must not suffice: the sender's Telegram
  identity must already be linked to the minter's PostHog account, and the minter
  must still be a member of the team's organization.
"""

import time
import secrets
from dataclasses import asdict, dataclass
from typing import Any, Literal
from uuid import UUID

from django.conf import settings
from django.core.cache import cache

import structlog

from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

from products.slack_app.backend.services.slack_user_oauth import _pick_accessible_linked_user

logger = structlog.get_logger(__name__)

_LINK_CODE_CACHE_PREFIX = "telegram_app:link_code:"
LINK_CODE_TTL_SECONDS = 15 * 60

LinkPurpose = Literal["link", "connect"]


@dataclass(frozen=True)
class TelegramLinkCode:
    purpose: LinkPurpose
    posthog_user_id: int
    team_id: int


def mint_link_code(*, purpose: LinkPurpose, posthog_user_id: int, team_id: int) -> str:
    # 24 random bytes → 32 chars of [A-Za-z0-9_-], comfortably inside Telegram's
    # 64-char /start payload limit.
    code = secrets.token_urlsafe(24)
    cache.set(
        _LINK_CODE_CACHE_PREFIX + code,
        asdict(TelegramLinkCode(purpose=purpose, posthog_user_id=posthog_user_id, team_id=team_id)),
        LINK_CODE_TTL_SECONDS,
    )
    return code


def redeem_link_code(code: str, *, expected_purpose: LinkPurpose) -> TelegramLinkCode | None:
    """One-shot: the code is deleted on first read regardless of purpose match."""
    if not code:
        return None
    key = _LINK_CODE_CACHE_PREFIX + code
    payload = cache.get(key)
    if payload is None:
        return None
    cache.delete(key)
    if not isinstance(payload, dict) or payload.get("purpose") != expected_purpose:
        return None
    try:
        return TelegramLinkCode(
            purpose=payload["purpose"],
            posthog_user_id=int(payload["posthog_user_id"]),
            team_id=int(payload["team_id"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def user_telegram_integration_from_identity(
    user: User, *, telegram_user_id: str, telegram_username: str | None
) -> UserIntegration:
    """Create or refresh the Telegram identity link.

    Symmetric with the GitHub/Slack personal integrations, minus ``sensitive_config``:
    Telegram issues no user token — the central bot is the only credential.
    """
    integration, _created = UserIntegration.objects.update_or_create(
        user=user,
        kind=UserIntegration.IntegrationKind.TELEGRAM,
        integration_id=telegram_user_id,
        defaults={
            "config": {
                "telegram_username": telegram_username,
                "linked_at": int(time.time()),
            },
        },
    )
    return integration


def find_linked_telegram_user(*, telegram_user_id: str, candidate_org_ids: set[UUID]) -> User | None:
    """The PostHog user linked to this Telegram identity, scoped to the candidate orgs.

    No workspace filter, unlike Slack: the bot is central and Telegram user ids are
    global, so one link row serves every chat.
    """
    if not telegram_user_id or not candidate_org_ids:
        return None
    try:
        links = list(
            UserIntegration.objects.filter(
                kind=UserIntegration.IntegrationKind.TELEGRAM,
                integration_id=telegram_user_id,
            )
            .select_related("user")
            .order_by("-created_at")
        )
        return _pick_accessible_linked_user(
            links,
            candidate_org_ids,
            warn_log_fields={"telegram_user_id": telegram_user_id},
        )
    except Exception:
        logger.warning(
            "slack_app_telegram_user_link_lookup_failed",
            telegram_user_id=telegram_user_id,
            exc_info=True,
        )
        return None


def bind_chat_to_team(*, team: Team, chat: dict[str, Any], bound_by_user_id: int) -> Integration | None:
    """Bind a Telegram chat (DM or group) to a team via an Integration row.

    Returns ``None`` when the chat is already bound to a different team — a chat
    belongs to exactly one project, and silently rebinding would let a second org
    steal an already-connected chat.
    """
    chat_id = str(chat.get("id") or "")
    if not chat_id:
        return None
    if Integration.objects.filter(kind="telegram", integration_id=chat_id).exclude(team_id=team.id).exists():
        return None
    config: dict[str, Any] = {
        "chat_type": chat.get("type"),
        "title": chat.get("title"),
        "bound_by_user_id": bound_by_user_id,
        "linked_at": int(time.time()),
    }
    integration, _created = Integration.objects.update_or_create(
        team=team,
        kind="telegram",
        integration_id=chat_id,
        defaults={"config": config},
    )
    return integration


def _command_argument(text: str, command: str) -> str | None:
    """Extract the argument of ``/command arg`` or ``/command@BotName arg``.

    Returns ``None`` when the text isn't that command, and ``""`` for the bare form.
    """
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    head, _, rest = stripped.partition(" ")
    name = head[1:].split("@", 1)[0]
    if name != command:
        return None
    return rest.strip()


def handle_start_redemption(message: dict[str, Any]) -> str:
    """Redeem ``/start <code>`` in a DM; returns the reply text."""
    sender = message.get("from") or {}
    telegram_user_id = str(sender.get("id") or "")
    code = _command_argument(str(message.get("text") or ""), "start")
    link_url = f"{settings.SITE_URL}/telegram/link/start/"

    if not code:
        return (
            "Hi! I'm the PostHog bot. To get started, link your PostHog account: "
            f"open {link_url}?team_id=<your project id> while logged in to PostHog."
        )

    payload = redeem_link_code(code, expected_purpose="link")
    if payload is None:
        return f"That link has expired or was already used. Start again from {link_url}?team_id=<your project id>."

    team = Team.objects.filter(id=payload.team_id).select_related("organization").first()
    user = User.objects.filter(id=payload.posthog_user_id).first()
    if team is None or user is None:
        return "Something's off with that link — the project or account behind it no longer exists."

    if not OrganizationMembership.objects.filter(user_id=user.id, organization_id=team.organization_id).exists():
        logger.warning(
            "slack_app_telegram_link_org_mismatch",
            posthog_user_id=user.id,
            team_id=team.id,
            telegram_user_id=telegram_user_id,
        )
        return "The account behind that link isn't a member of the project's organization anymore."

    user_telegram_integration_from_identity(
        user,
        telegram_user_id=telegram_user_id,
        telegram_username=sender.get("username"),
    )
    logger.info(
        "slack_app_telegram_identity_linked",
        posthog_user_id=user.id,
        telegram_user_id=telegram_user_id,
        team_id=team.id,
    )

    bound = bind_chat_to_team(team=team, chat=message.get("chat") or {}, bound_by_user_id=user.id)
    if bound is None:
        return (
            "Your account is linked, but this chat is already connected to another PostHog project, "
            "so I left that connection alone."
        )
    return f"You're all set — your account is linked and this chat is connected to {team.name}. Mention me with a task to get started."


def handle_connect_redemption(message: dict[str, Any]) -> str:
    """Redeem ``/connect <code>`` in a group; returns the reply text."""
    sender = message.get("from") or {}
    telegram_user_id = str(sender.get("id") or "")
    code = _command_argument(str(message.get("text") or ""), "connect")
    connect_url = f"{settings.SITE_URL}/telegram/connect/start/"

    if not code:
        return f"Usage: /connect <code> — get a code from {connect_url}?team_id=<your project id> while logged in to PostHog."

    payload = redeem_link_code(code, expected_purpose="connect")
    if payload is None:
        return (
            f"That code has expired or was already used. Get a fresh one from {connect_url}?team_id=<your project id>."
        )

    sender_links = list(
        UserIntegration.objects.filter(
            kind=UserIntegration.IntegrationKind.TELEGRAM,
            integration_id=telegram_user_id,
        )
    )
    if not sender_links:
        return (
            "Link your PostHog account first: DM me after opening "
            f"{settings.SITE_URL}/telegram/link/start/?team_id=<your project id>, then paste the code again."
        )
    if not any(link.user_id == payload.posthog_user_id for link in sender_links):
        logger.warning(
            "slack_app_telegram_connect_minter_mismatch",
            telegram_user_id=telegram_user_id,
            minter_posthog_user_id=payload.posthog_user_id,
        )
        return "Only the person who generated this code in PostHog can use it."

    team = Team.objects.filter(id=payload.team_id).select_related("organization").first()
    if team is None:
        return "The project behind that code no longer exists."
    if not OrganizationMembership.objects.filter(
        user_id=payload.posthog_user_id, organization_id=team.organization_id
    ).exists():
        return "The account behind that code isn't a member of the project's organization anymore."

    bound = bind_chat_to_team(team=team, chat=message.get("chat") or {}, bound_by_user_id=payload.posthog_user_id)
    if bound is None:
        return "This chat is already connected to another PostHog project."
    return (
        f"Connected this chat to {team.name}. Anyone here with a linked PostHog account can now mention me with a task."
    )
