"""Read helpers for per-(Slack workspace, Slack user) settings backed by
`models.SlackSettings` (today: the untagged follow-up and question modes, the thread
join mode, the channel welcome mode and the automatic model choice), plus the shared
AI-triple value object.

Model preferences themselves live in the central tasks config
(`products.tasks.backend.facade.ai_run_defaults`); `AIPreferences` keeps the
task-run serializer's field names so resolver output can be handed to the task
layer with zero translation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from django.db import models

from products.slack_app.backend.models import ChannelWelcomeMode, ThreadJoinMode, UntaggedFollowupMode
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration

_Mode = TypeVar("_Mode", bound=models.TextChoices)


@dataclass(frozen=True)
class AIPreferences:
    """A resolved AI-preference triple.

    Field names match the task-run request serializer so callers can splat this
    straight into the task creation payload.
    """

    runtime_adapter: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None


def resolve_untagged_followup_mode(
    integration: WorkspaceIntegration, slack_user_id: str | None
) -> UntaggedFollowupMode:
    """Resolve how untagged replies in a thread this Slack user started are treated.

    Read from the thread creator's row, so one person's choice governs every
    reply in the threads they started. An absent row or empty column resolves
    to `ASK`, so the replier chooses whether to send the message. An unknown
    value resolves to `NEVER`.
    """
    return _resolve_untagged_mode(integration.integration_id, slack_user_id, "untagged_followup_mode")


def resolve_untagged_question_mode(slack_workspace_id: str, slack_user_id: str | None) -> UntaggedFollowupMode:
    """Resolve what PostHog does with this Slack user's top-level channel questions that do not tag it.

    Read from the author's own row, so one person's choice never changes what happens
    to anyone else's messages. An absent row or empty column resolves to `ASK`: PostHog
    offers privately and answers only after the author confirms. An unknown value
    resolves to `NEVER`.
    """
    return _resolve_untagged_mode(slack_workspace_id, slack_user_id, "untagged_question_mode")


def _resolve_untagged_mode(slack_workspace_id: str, slack_user_id: str | None, column: str) -> UntaggedFollowupMode:
    if not slack_user_id:
        return UntaggedFollowupMode.NEVER
    return _resolve_personal_mode(
        slack_workspace_id,
        slack_user_id,
        column,
        UntaggedFollowupMode,
        unset=UntaggedFollowupMode.ASK,
        unknown=UntaggedFollowupMode.NEVER,
    )


def _resolve_personal_mode(
    slack_workspace_id: str, slack_user_id: str, column: str, mode_type: type[_Mode], *, unset: _Mode, unknown: _Mode
) -> _Mode:
    """One choice from a Slack user's personal settings row, as `mode_type`."""
    from products.slack_app.backend.models import SlackSettings

    stored = (
        SlackSettings.objects.filter(slack_workspace_id=slack_workspace_id, slack_user_id=slack_user_id)
        .values_list(column, flat=True)
        .first()
    )
    if stored is None:
        return unset
    if stored in mode_type.values:
        return mode_type(stored)
    return unknown


def set_untagged_followup_mode(slack_workspace_id: str, slack_user_id: str, mode: UntaggedFollowupMode) -> None:
    _set_untagged_mode(slack_workspace_id, slack_user_id, "untagged_followup_mode", mode)


def set_untagged_question_mode(slack_workspace_id: str, slack_user_id: str, mode: UntaggedFollowupMode) -> None:
    _set_untagged_mode(slack_workspace_id, slack_user_id, "untagged_question_mode", mode)


def set_thread_join_mode(slack_workspace_id: str, slack_user_id: str, mode: ThreadJoinMode) -> None:
    _set_untagged_mode(slack_workspace_id, slack_user_id, "thread_join_mode", mode)


def _set_untagged_mode(slack_workspace_id: str, slack_user_id: str, column: str, mode: models.TextChoices) -> None:
    from products.slack_app.backend.models import SlackSettings

    SlackSettings.objects.update_or_create(
        slack_workspace_id=slack_workspace_id,
        slack_user_id=slack_user_id,
        defaults={column: mode.value},
    )


def resolve_thread_join_mode(
    integration: WorkspaceIntegration, slack_user_id: str | None, *, own_subscription: bool = False
) -> ThreadJoinMode:
    """Resolve what happens when someone else tags PostHog in a thread this Slack user started.

    An absent row or empty column resolves to `ALLOW`, so anyone can join until the creator picks
    a stricter mode. When the thread's run bills to the creator's own plan, it resolves to
    `ASK_PER_THREAD` instead, so nobody uses that plan before the creator approves.
    An unknown value resolves to `NEVER`.
    """
    if not slack_user_id:
        return ThreadJoinMode.ALLOW
    return _resolve_personal_mode(
        integration.integration_id,
        slack_user_id,
        "thread_join_mode",
        ThreadJoinMode,
        unset=ThreadJoinMode.ASK_PER_THREAD if own_subscription else ThreadJoinMode.ALLOW,
        unknown=ThreadJoinMode.NEVER,
    )


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
    "resolve_untagged_question_mode",
    "set_auto_model_choice",
    "set_untagged_followup_mode",
    "set_untagged_question_mode",
    "set_channel_welcome_mode",
    "resolve_thread_join_mode",
    "set_thread_join_mode",
    "resolve_untagged_followup_mode",
]
