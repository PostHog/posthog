"""Inbox onboarding DM: a product intro built from four steps (GitHub, sources, reports/channel, AI approval).

Block builders assemble the message, ``send_onboarding_dm`` delivers it, and the interactivity helpers
(called from ``api.py``) handle each click. ``run_install_onboarding`` is the install entrypoint.
"""

from __future__ import annotations

import json
from enum import StrEnum

from django.conf import settings

import structlog
from slack_sdk.errors import SlackApiError

from posthog.models import OrganizationMembership, Team
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.user_integration import UserIntegration
from posthog.utils import absolute_uri

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.inbox_channel import (
    INBOX_CHANNEL_REQUIRED_SCOPES,
    _channel_exists,
    _get_team_channel,
    _is_channel_member,
    channel_id_from_target,
    channel_name_from_target,
    ensure_inbox_channel,
    has_inbox_scopes,
    invite_user_to_inbox,
)

logger = structlog.get_logger(__name__)

# Block Kit action ids for the onboarding DM, kept in sync with the interactivity router.
INBOX_CREATE_ACTION_ID = "slack_inbox_create"
INBOX_JOIN_ACTION_ID = "slack_inbox_join"
# The block_id carries the integration id so the checkbox interaction can be region-routed.
INBOX_SOURCES_CHECKBOXES_ACTION = "slack_inbox_sources_select"
INBOX_SOURCES_BLOCK_PREFIX = "slack_inbox_sources_block"
# AI approval is a hard prerequisite — without it no signals are emitted. block_id carries the integration id.
INBOX_AI_APPROVAL_ACTION_ID = "slack_inbox_ai_approval"
INBOX_AI_APPROVAL_BLOCK_PREFIX = "slack_inbox_ai_approval_block"


class OnboardingStep(StrEnum):
    AI_APPROVAL = "ai_approval"
    CHANNEL = "channel"
    GITHUB = "github"
    SOURCES = "sources"


EVENT_DM_SENT = "slack_onboarding_dm_sent"
EVENT_STEP_COMPLETED = "slack_onboarding_step_completed"
EVENT_COMPLETED = "slack_onboarding_completed"
EVENT_SOURCE_ENABLED = "slack_onboarding_source_enabled"

_REQUIRED_STEPS = (OnboardingStep.AI_APPROVAL, OnboardingStep.CHANNEL, OnboardingStep.GITHUB, OnboardingStep.SOURCES)


# =====================================================================
# Block Kit primitives + per-step block builders
# =====================================================================


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _button(label: str, action_id: str, value: str) -> dict:
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": label},
        "action_id": action_id,
        "value": value,
        "style": "primary",
    }


def _public_url(path: str) -> str:
    """Public base URL for links delivered to Slack. In local dev, prefer the ngrok tunnel so the link
    is reachable from outside (mirrors ``OauthIntegration.redirect_uri``)."""
    if settings.DEBUG and settings.NGROK_URL:
        return f"{settings.NGROK_URL.rstrip('/')}{path}"
    return absolute_uri(path)


def _done(text: str) -> dict:
    return _context(f":white_check_mark: {text}")


def _context(text: str) -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _github_connect_url(team_id: int) -> str:
    """GitHub OAuth entry that returns to Slack — one flow connects the team install and the user's personal GitHub."""
    return _public_url(f"/integrations/connect/github/?project_id={team_id}&connect_from=slack")


def _github_blocks(integration: Integration, *, done: bool) -> list[dict]:
    blocks: list[dict] = [
        _section(
            "*1. Connect your codebase* :wrench:\nConnect GitHub so I can fix things, not just flag them - "
            "when I spot a problem in your product I'll proactively open a pull request with the fix for you to review."
        )
    ]
    if done:
        blocks.append(_done("Connected"))
        return blocks
    # Pure URL button (no action_id): clicking just opens OAuth in the browser and fires no
    # interaction. The callback returns to Slack; the message updates next time it's rebuilt.
    button = {
        "type": "button",
        "text": {"type": "plain_text", "text": "Connect GitHub"},
        "url": _github_connect_url(integration.team_id),
        "style": "primary",
    }
    blocks.append({"type": "actions", "elements": [button]})
    return blocks


def _sources_blocks(integration: Integration) -> list[dict]:
    """Inline checkboxes (current state pre-checked) — ticking sets a source up immediately, unticking turns it off."""
    from products.signals.backend.facade.api import (
        onboarding_sources,  # noqa: PLC0415 — keeps the signals stack off the slack import path
    )

    sources = onboarding_sources(integration.team_id)
    options = [
        {
            "text": {"type": "mrkdwn", "text": f"*{source.label}*: {source.description}"},
            "value": source.key,
        }
        for source in sources
    ]
    checkboxes: dict = {"type": "checkboxes", "action_id": INBOX_SOURCES_CHECKBOXES_ACTION, "options": options}
    initial = [option for option, source in zip(options, sources) if source.enabled]
    if initial:
        checkboxes["initial_options"] = initial
    return [
        _section("*2. Choose what I watch* :eyes:\nTick the signals I should monitor and investigate."),
        {"type": "actions", "block_id": f"{INBOX_SOURCES_BLOCK_PREFIX}:{integration.id}", "elements": [checkboxes]},
    ]


def _channel_blocks(integration: Integration, slack: SlackIntegration, *, done: bool) -> list[dict]:
    blocks: list[dict] = [
        _section(
            "*3. Where I report* :inbox_tray:\nEverything I find lands in one shared channel so the team stays in the loop."
        )
    ]
    if done:
        blocks.append(_done("Posting to #posthog-inbox"))
        return blocks
    configured = _get_team_channel(integration.team_id)
    channel_exists = configured is not None and _channel_exists(slack, channel_id_from_target(configured))
    has_scope = not slack.missing_scopes(INBOX_CHANNEL_REQUIRED_SCOPES)
    value = json.dumps({"integration_id": integration.id})
    name = channel_name_from_target(configured or "") if channel_exists else "#posthog-inbox"
    if channel_exists and has_scope:
        blocks.append({"type": "actions", "elements": [_button(f"Join {name}", INBOX_JOIN_ACTION_ID, value)]})
    elif channel_exists:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"Join {name} in your workspace."}]})
    elif has_scope:
        blocks.append(
            {"type": "actions", "elements": [_button("Create #posthog-inbox", INBOX_CREATE_ACTION_ID, value)]}
        )
    else:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Create a #posthog-inbox channel, then set it in your <{_public_url('/inbox')}|inbox>.",
                    }
                ],
            }
        )
    return blocks


def _ai_approval_blocks(integration: Integration, *, is_admin: bool) -> list[dict]:
    """The approval prompt — only rendered when not yet approved. Admins tick a checkbox to approve;
    non-admins get an 'ask an admin' note, since only ADMIN+ can toggle org settings."""
    blocks: list[dict] = [
        _section(
            "*4. Approve AI data processing*\nTo investigate your product I use external AI "
            "providers (Anthropic, OpenAI, Google, Microsoft). This can involve transferring identifying user data, "
            "and is never used to train third-party models. FYI it's not HIPAA-compliant yet, and any BAA you have "
            "with PostHog won't cover these features."
        )
    ]
    if not is_admin:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": ":warning: Ask an org admin to approve. Until then I can't get started.",
                    }
                ],
            }
        )
        return blocks
    blocks.append(
        {
            "type": "actions",
            "block_id": f"{INBOX_AI_APPROVAL_BLOCK_PREFIX}:{integration.id}",
            "elements": [
                {
                    "type": "checkboxes",
                    "action_id": INBOX_AI_APPROVAL_ACTION_ID,
                    "options": [
                        {"text": {"type": "plain_text", "text": "Approve AI data processing"}, "value": "approve"}
                    ],
                }
            ],
        }
    )
    return blocks


# Slack has no disabled buttons; a context block is the idiomatic greyed/done state.
def _replace_actions_with_context(blocks: list[dict], action_ids: set[str], text: str) -> list[dict]:
    return [
        _context(text)
        if (
            block.get("type") == "actions"
            and any(el.get("action_id") in action_ids for el in block.get("elements", []))
        )
        else block
        for block in blocks
    ]


# =====================================================================
# Assembly, delivery, status, completion
# =====================================================================


def build_onboarding_dm(
    integration: Integration,
    slack: SlackIntegration,
    *,
    needs_ai_approval: bool = False,
    ai_approval_is_admin: bool = True,
    needs_github: bool = False,
    already_in_channel: bool = False,
) -> tuple[str, list[dict]]:
    """Return (fallback_text, Block Kit blocks) for the inbox onboarding DM.

    Every step is always shown with its state (done steps render a '✅' line). AI approval is the one
    exception: omitted once approved. Always returns a full message — the DM is posted unconditionally.
    """
    intro = _section(
        "👋 *Hi, I'm PostHog - self-driving for your product*\nI'm an AI agent on autopilot: I watch your product "
        "for problems, investigate them myself, and open pull requests to fix them - so issues get handled before "
        "they reach your backlog."
    )
    blocks: list[dict] = [intro, {"type": "divider"}]
    blocks += _github_blocks(integration, done=not needs_github)
    blocks += _sources_blocks(integration)
    blocks += _channel_blocks(integration, slack, done=already_in_channel)
    if needs_ai_approval:
        blocks += _ai_approval_blocks(integration, is_admin=ai_approval_is_admin)
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "🎉 Once you're set up, I'll start watching your product and send your first report to #posthog-inbox as soon as I spot something.",
                }
            ],
        }
    )
    return "Set up PostHog - self-driving for your product", blocks


def _has_team_github(team_id: int) -> bool:
    return Integration.objects.filter(team_id=team_id, kind="github").exists()


def _has_personal_github(user_id: int) -> bool:
    return UserIntegration.objects.filter(user_id=user_id, kind=UserIntegration.IntegrationKind.GITHUB).exists()


def _has_ai_approval(team_id: int) -> bool:
    org_approved = (
        Team.objects.filter(id=team_id).values_list("organization__is_ai_data_processing_approved", flat=True).first()
    )
    return bool(org_approved)


def _is_org_admin(user_id: int, team_id: int) -> bool:
    """Whether the user can toggle org settings (AI consent needs ADMIN+)."""
    org_id = Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()
    if org_id is None:
        return False
    level = (
        OrganizationMembership.objects.filter(organization_id=org_id, user_id=user_id)
        .values_list("level", flat=True)
        .first()
    )
    return level is not None and level >= OrganizationMembership.Level.ADMIN


def _has_enabled_source(team_id: int) -> bool:
    from products.signals.backend.facade.api import (
        has_enabled_source,  # noqa: PLC0415 — keeps the signals stack off the slack import path
    )

    return has_enabled_source(team_id)


def _resolve_onboarding_user(slack: SlackIntegration, integration: Integration, slack_user_id: str) -> int | None:
    """Resolve the Slack user to a PostHog user id (org-member email match), or None."""
    from products.slack_app.backend.api import (
        resolve_slack_user,  # noqa: PLC0415 — api.py imports this module; defer to break the cycle
    )

    context = resolve_slack_user(slack, integration, slack_user_id, "", "", post_feedback=False)
    return context.user.id if context else None


def _onboarding_status(
    integration: Integration, slack: SlackIntegration, slack_user_id: str, user_id: int | None = None
) -> tuple[int | None, dict[OnboardingStep, bool]]:
    """Resolve the user and evaluate each step's done/not-done — the source of truth for what's left.
    Pass ``user_id`` when the caller already resolved it, to skip the repeat lookup."""
    # GitHub is done only when both the team install and the user's personal GitHub exist.
    if user_id is None:
        user_id = _resolve_onboarding_user(slack, integration, slack_user_id)
    team_id = integration.team_id
    configured = _get_team_channel(team_id)
    in_channel = configured is not None and _is_channel_member(slack, channel_id_from_target(configured), slack_user_id)
    return user_id, {
        OnboardingStep.AI_APPROVAL: _has_ai_approval(team_id),
        OnboardingStep.CHANNEL: in_channel,
        OnboardingStep.GITHUB: (user_id is None or _has_personal_github(user_id)) and _has_team_github(team_id),
        OnboardingStep.SOURCES: _has_enabled_source(team_id),
    }


def _build_from_status(
    integration: Integration, slack: SlackIntegration, user_id: int | None, status: dict[OnboardingStep, bool]
) -> tuple[str, list[dict]]:
    is_admin = user_id is not None and _is_org_admin(user_id, integration.team_id)
    return build_onboarding_dm(
        integration,
        slack,
        needs_ai_approval=not status[OnboardingStep.AI_APPROVAL],
        ai_approval_is_admin=is_admin,
        needs_github=not status[OnboardingStep.GITHUB],
        already_in_channel=status[OnboardingStep.CHANNEL],
    )


def send_onboarding_dm(integration: Integration, slack_user_id: str) -> bool:
    """DM a user the inbox onboarding. Returns True when sent, False when the post failed.

    Always posts (no dedupe, no all-done shortcut) — the install hook already fires only once.
    """
    if not slack_user_id:
        return False
    slack = SlackIntegration(integration)
    user_id, status = _onboarding_status(integration, slack, slack_user_id)
    text, blocks = _build_from_status(integration, slack, user_id, status)
    try:
        slack.client.chat_postMessage(channel=slack_user_id, text=text, blocks=blocks)
    except SlackApiError as e:
        logger.warning("slack_inbox_onboarding_dm_failed", integration_id=integration.id, error=e.response.get("error"))
        return False
    capture_slack_event(
        integration,
        EVENT_DM_SENT,
        slack_user_id=slack_user_id,
        steps_needed=[str(step) for step, done in status.items() if not done],
        steps_total=len(status),
        is_admin=user_id is not None and _is_org_admin(user_id, integration.team_id),
    )
    return True


def _maybe_complete(integration: Integration, slack_user_id: str, user_id: int | None = None) -> None:
    """Fire 'completed' once every required step is done. Pass ``user_id`` when already resolved."""
    _, status = _onboarding_status(integration, SlackIntegration(integration), slack_user_id, user_id)
    if all(status[step] for step in _REQUIRED_STEPS):
        capture_slack_event(integration, EVENT_COMPLETED, slack_user_id=slack_user_id)


# =====================================================================
# Interactivity: click handlers (called from api.py's router)
# =====================================================================


def _chat_update_blocks(integration: Integration, channel: str, message_ts: str, text: str, blocks: list[dict]) -> None:
    try:
        SlackIntegration(integration).client.chat_update(channel=channel, ts=message_ts, text=text, blocks=blocks)
    except SlackApiError as e:
        logger.warning(
            "slack_inbox_connect_update_failed", integration_id=integration.id, error=e.response.get("error")
        )


def mark_channel_joined(
    integration: Integration, slack_user_id: str, channel: str, message_ts: str, original_blocks: list[dict]
) -> None:
    """After create/join: flip just the channel block to a '✅' line in place, then record completion."""
    swapped = _replace_actions_with_context(
        original_blocks,
        {INBOX_CREATE_ACTION_ID, INBOX_JOIN_ACTION_ID},
        ":white_check_mark: You're in your #posthog-inbox channel",
    )
    _chat_update_blocks(integration, channel, message_ts, "You're in your #posthog-inbox channel", swapped)
    capture_slack_event(
        integration, EVENT_STEP_COMPLETED, slack_user_id=slack_user_id, step=str(OnboardingStep.CHANNEL)
    )
    _maybe_complete(integration, slack_user_id)


def apply_sources_selection(integration: Integration, slack_user_id: str, selected_keys: list[str]) -> list[str]:
    """Sync the team's sources to the new selection. Returns the labels of any that couldn't be turned
    on (AI data processing not approved yet)."""
    from products.signals.backend.facade.api import (
        set_sources,  # noqa: PLC0415 — keeps the signals stack off the slack import path
    )

    user_id = _resolve_onboarding_user(SlackIntegration(integration), integration, slack_user_id)
    if user_id is None:
        # Can't tie the clicker to an org member — don't mutate team state.
        return []
    blocked = set_sources(integration.team_id, user_id, selected_keys)
    capture_slack_event(
        integration, EVENT_SOURCE_ENABLED, slack_user_id=slack_user_id, selected=list(selected_keys), blocked=blocked
    )
    _maybe_complete(integration, slack_user_id, user_id)
    return blocked


def approve_ai_data_processing(integration: Integration, slack_user_id: str) -> bool:
    """Admin-only approval: re-checks ADMIN+ server-side, sets org consent, records completion.
    Returns False if the clicker isn't an admin."""
    user_id = _resolve_onboarding_user(SlackIntegration(integration), integration, slack_user_id)
    if user_id is None or not _is_org_admin(user_id, integration.team_id):
        return False
    org_id = Team.objects.filter(id=integration.team_id).values_list("organization_id", flat=True).first()
    if org_id is None:
        return False
    from posthog.models.organization import Organization  # noqa: PLC0415

    # Save the instance (not a queryset .update()) so ModelActivityMixin records the consent change
    # in the activity log and updated_at is bumped.
    organization = Organization.objects.filter(id=org_id).first()
    if organization is None:
        return False
    organization.is_ai_data_processing_approved = True
    organization.save(update_fields=["is_ai_data_processing_approved", "updated_at"])
    capture_slack_event(
        integration, EVENT_STEP_COMPLETED, slack_user_id=slack_user_id, step=str(OnboardingStep.AI_APPROVAL)
    )
    _maybe_complete(integration, slack_user_id, user_id)
    return True


def run_install_onboarding(integration: Integration) -> None:
    """On a fresh install: create the inbox channel, invite the installer, and DM them the onboarding.
    Gated on the install having ``channels:manage``; best-effort."""
    if not has_inbox_scopes(integration):
        return
    channel = ensure_inbox_channel(integration)
    installer = ((integration.config or {}).get("authed_user") or {}).get("id")
    if not installer:
        return
    if channel is not None:
        invite_user_to_inbox(integration, channel[0], installer)
    send_onboarding_dm(integration, installer)
