"""Read helpers for per-(Slack workspace, Slack user) settings backed by
`models.SlackSettings` (today: the untagged follow-up and question modes, the thread
join mode, the channel welcome mode, the automatic model choice and where the DM setup
card is), plus the shared AI-triple value object.

Model preferences themselves live in the central tasks config
(`products.tasks.backend.facade.ai_run_defaults`); `AIPreferences` keeps the
task-run serializer's field names so resolver output can be handed to the task
layer with zero translation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from django.db import models, transaction

from posthog.dataclasses import frozen

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


def resolve_thread_join_mode(integration: WorkspaceIntegration, slack_user_id: str | None) -> ThreadJoinMode:
    """Resolve what happens when someone else tags PostHog in a thread this Slack user started.

    An absent row or empty column resolves to `ALLOW`, also when the run bills to the creator's own
    plan, so anyone can join until the creator picks a stricter mode.
    An unknown value resolves to `NEVER`.
    """
    if not slack_user_id:
        return ThreadJoinMode.ALLOW
    return _resolve_personal_mode(
        integration.integration_id,
        slack_user_id,
        "thread_join_mode",
        ThreadJoinMode,
        unset=ThreadJoinMode.ALLOW,
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


@frozen
class DmSetupCardState:
    """A person's DM setup card. ``ts`` is None when PostHog found nothing to set up and posted no card."""

    channel: str | None
    ts: str | None
    completed: bool
    skipped: tuple[str, ...]


def resolve_dm_setup_card(slack_workspace_id: str, slack_user_id: str) -> DmSetupCardState | None:
    from products.slack_app.backend.models import SlackSettings

    stored = (
        SlackSettings.objects.filter(slack_workspace_id=slack_workspace_id, slack_user_id=slack_user_id)
        .values_list("dm_setup_card", flat=True)
        .first()
    )
    if not isinstance(stored, dict):
        return None
    skipped = stored.get("skipped")
    return DmSetupCardState(
        channel=stored.get("channel") or None,
        ts=stored.get("ts") or None,
        completed=bool(stored.get("completed")),
        skipped=tuple(str(key) for key in skipped) if isinstance(skipped, list) else (),
    )


def update_dm_setup_card(
    slack_workspace_id: str,
    slack_user_id: str,
    *,
    channel: str | None = None,
    ts: str | None = None,
    completed: bool | None = None,
    skip_step: str | None = None,
) -> None:
    """Change only the given parts. The row lock keeps a skip click and a render from losing each other's write."""
    from products.slack_app.backend.models import SlackSettings

    with transaction.atomic():
        row, _ = SlackSettings.objects.select_for_update().get_or_create(
            slack_workspace_id=slack_workspace_id, slack_user_id=slack_user_id
        )
        card = dict(row.dm_setup_card) if isinstance(row.dm_setup_card, dict) else {}
        if channel is not None and ts is not None:
            card["channel"], card["ts"] = channel, ts
        if completed is not None:
            card["completed"] = completed
        if skip_step is not None:
            skipped = [key for key in card.get("skipped") or [] if key != skip_step]
            card["skipped"] = [*skipped, skip_step]
        row.dm_setup_card = card
        row.save(update_fields=["dm_setup_card", "updated_at"])


def has_chosen_untagged_followup_mode(slack_workspace_id: str, slack_user_id: str) -> bool:
    """Whether this person picked a mode, as opposed to getting the ``ASK`` default."""
    from products.slack_app.backend.models import SlackSettings

    return SlackSettings.objects.filter(
        slack_workspace_id=slack_workspace_id, slack_user_id=slack_user_id, untagged_followup_mode__isnull=False
    ).exists()


def resolve_workspace_default_integration_id(slack_workspace_id: str) -> int | None:
    """The integration that the workspace-wide row routes mentions to."""

    from products.slack_app.backend.models import SlackSettings

    return (
        SlackSettings.objects.filter(slack_workspace_id=slack_workspace_id, slack_user_id__isnull=True)
        .values_list("default_integration_id", flat=True)
        .first()
    )


def set_workspace_default_integration(slack_workspace_id: str, integration_id: int) -> None:
    """The caller checks that the actor may set the default."""

    from products.slack_app.backend.models import SlackSettings

    SlackSettings.objects.update_or_create(
        slack_workspace_id=slack_workspace_id,
        slack_user_id=None,
        defaults={"default_integration_id": integration_id},
    )


__all__ = [
    "DmSetupCardState",
    "has_chosen_untagged_followup_mode",
    "resolve_dm_setup_card",
    "update_dm_setup_card",
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
    "resolve_workspace_default_integration_id",
    "set_workspace_default_integration",
]
