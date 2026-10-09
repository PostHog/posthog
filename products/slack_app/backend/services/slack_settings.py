"""Read helpers for per-(Slack workspace, Slack user) settings backed by
`models.SlackSettings` (today: the untagged follow-up mode, the channel
welcome mode and the automatic model choice), the per-channel ceiling on
unprompted answers backed by `models.SlackChannel`, plus the shared
AI-triple value object.

Model preferences themselves live in the central tasks config
(`products.tasks.backend.facade.ai_run_defaults`); `AIPreferences` keeps the
task-run serializer's field names so resolver output can be handed to the task
layer with zero translation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from products.slack_app.backend.models import ChannelWelcomeMode, UntaggedFollowupMode

if TYPE_CHECKING:
    from posthog.models.integration import Integration


@dataclass(frozen=True)
class AIPreferences:
    """A resolved AI-preference triple.

    Field names match the task-run request serializer so callers can splat this
    straight into the task creation payload.
    """

    runtime_adapter: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None


def resolve_untagged_followup_mode(integration: Integration, slack_user_id: str | None) -> UntaggedFollowupMode:
    """Resolve how untagged replies in a thread this Slack user started are treated.

    Read from the thread creator's row, so one person's choice governs every
    reply in the threads they started. An absent row or empty column resolves
    to `ASK`, so the replier chooses whether to send the message. An unknown
    value resolves to `NEVER`.
    """

    return resolve_user_untagged_mode(integration.integration_id, slack_user_id)


def resolve_user_untagged_mode(slack_workspace_id: str, slack_user_id: str | None) -> UntaggedFollowupMode:
    if not slack_user_id:
        return UntaggedFollowupMode.NEVER

    from products.slack_app.backend.models import SlackSettings

    row = (
        SlackSettings.objects.filter(slack_workspace_id=slack_workspace_id, slack_user_id=slack_user_id)
        .values("untagged_followup_mode")
        .first()
    )
    return _coerce_untagged_mode(row["untagged_followup_mode"] if row else None)


def set_untagged_followup_mode(slack_workspace_id: str, slack_user_id: str, mode: UntaggedFollowupMode) -> None:
    from products.slack_app.backend.models import SlackSettings

    SlackSettings.objects.update_or_create(
        slack_workspace_id=slack_workspace_id,
        slack_user_id=slack_user_id,
        defaults={"untagged_followup_mode": mode.value},
    )


def resolve_channel_unprompted_answer_mode(
    slack_workspace_id: str, slack_channel_id: str | None
) -> UntaggedFollowupMode:
    """The most PostHog may do with an untagged top-level question in this channel.

    An absent row or empty column resolves to `ASK`, so a channel nobody configured
    never gets a public answer that nobody clicked for. An unknown value resolves to `NEVER`.
    """

    if not slack_channel_id:
        return UntaggedFollowupMode.NEVER

    from products.slack_app.backend.models import SlackChannel

    stored = (
        SlackChannel.objects.filter(slack_workspace_id=slack_workspace_id, slack_channel_id=slack_channel_id)
        .values_list("unprompted_answer_mode", flat=True)
        .first()
    )
    return _coerce_untagged_mode(stored)


def set_channel_unprompted_answer_mode(
    slack_workspace_id: str, slack_channel_id: str, mode: UntaggedFollowupMode
) -> None:
    """Store the channel ceiling. The caller decides whether the actor may loosen it."""

    from products.slack_app.backend.models import SlackChannel

    SlackChannel.objects.update_or_create(
        slack_workspace_id=slack_workspace_id,
        slack_channel_id=slack_channel_id,
        defaults={"unprompted_answer_mode": mode.value},
    )


def is_stricter_untagged_mode(candidate: UntaggedFollowupMode, than: UntaggedFollowupMode) -> bool:
    return _UNTAGGED_MODE_STRICTNESS[candidate] > _UNTAGGED_MODE_STRICTNESS[than]


def resolve_unprompted_question_mode(
    slack_workspace_id: str, slack_channel_id: str | None, slack_user_id: str | None
) -> UntaggedFollowupMode:
    """What PostHog does with an untagged top-level question: the stricter of the author's mode and the channel's.

    Neither side overrides the other. The answer is public, so the channel can hold it back for
    everyone who reads there, and the author can hold it back for their own messages in any channel.
    """

    user_mode = resolve_user_untagged_mode(slack_workspace_id, slack_user_id)
    if user_mode == UntaggedFollowupMode.NEVER:
        return user_mode
    channel_mode = resolve_channel_unprompted_answer_mode(slack_workspace_id, slack_channel_id)
    return channel_mode if is_stricter_untagged_mode(channel_mode, user_mode) else user_mode


_UNTAGGED_MODE_STRICTNESS: dict[UntaggedFollowupMode, int] = {
    UntaggedFollowupMode.AUTO: 0,
    UntaggedFollowupMode.ASK: 1,
    UntaggedFollowupMode.NEVER: 2,
}


def _coerce_untagged_mode(stored: str | None) -> UntaggedFollowupMode:
    if stored is None:
        return UntaggedFollowupMode.ASK
    if stored in UntaggedFollowupMode.values:
        return UntaggedFollowupMode(stored)
    return UntaggedFollowupMode.NEVER


def resolve_channel_welcome_mode(slack_workspace_id: str) -> ChannelWelcomeMode:
    """Resolve where the greeting goes when someone adds the app to a channel.

    Read from the workspace-wide row. An absent row or empty column resolves to
    `CHANNEL`. An unknown value resolves to `OFF`, so a bad value never posts
    to a channel.
    """

    from products.slack_app.backend.models import SlackSettings

    stored = (
        SlackSettings.objects.filter(slack_workspace_id=slack_workspace_id, slack_user_id__isnull=True)
        .values_list("channel_welcome_mode", flat=True)
        .first()
    )
    if stored is None:
        return ChannelWelcomeMode.CHANNEL
    if stored in ChannelWelcomeMode.values:
        return ChannelWelcomeMode(stored)
    return ChannelWelcomeMode.OFF


def set_channel_welcome_mode(slack_workspace_id: str, mode: ChannelWelcomeMode) -> None:
    """Store the mode on the workspace-wide row. The caller checks that the actor is a Slack admin."""

    from products.slack_app.backend.models import SlackSettings

    SlackSettings.objects.update_or_create(
        slack_workspace_id=slack_workspace_id,
        slack_user_id=None,
        defaults={"channel_welcome_mode": mode.value},
    )


def resolve_auto_model_choice(slack_workspace_id: str, slack_user_id: str | None) -> bool:
    if not slack_user_id:
        return False

    from products.slack_app.backend.models import SlackSettings

    return bool(
        SlackSettings.objects.filter(slack_workspace_id=slack_workspace_id, slack_user_id=slack_user_id)
        .values_list("auto_model_choice", flat=True)
        .first()
    )


def set_auto_model_choice(slack_workspace_id: str, slack_user_id: str, enabled: bool) -> None:
    from products.slack_app.backend.models import SlackSettings

    SlackSettings.objects.update_or_create(
        slack_workspace_id=slack_workspace_id,
        slack_user_id=slack_user_id,
        defaults={"auto_model_choice": enabled},
    )


__all__ = [
    "AIPreferences",
    "resolve_auto_model_choice",
    "resolve_channel_welcome_mode",
    "is_stricter_untagged_mode",
    "resolve_channel_unprompted_answer_mode",
    "resolve_unprompted_question_mode",
    "resolve_user_untagged_mode",
    "set_auto_model_choice",
    "set_channel_unprompted_answer_mode",
    "set_untagged_followup_mode",
    "set_channel_welcome_mode",
    "resolve_untagged_followup_mode",
]
