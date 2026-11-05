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
from typing import Literal, TypeVar

from django.db import models, transaction
from django.utils import timezone

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


# Bump when onboarding gains steps that people who already finished it should see.
ONBOARDING_VERSION = 1

OnboardingCompletedReason = Literal["finished", "nothing_to_set_up", "legacy"]


@frozen(slots=False)
class OnboardingState:
    """A person's onboarding thread in the PostHog DM. ``root_ts`` is None until the top message is posted,
    and stays None when there was nothing to set up. ``completed_reason`` is "legacy" for people who used
    the app before onboarding existed."""

    channel: str | None
    root_ts: str | None
    progress: str | None
    step_ts: dict[str, str]
    summarized: tuple[str, ...]
    skipped: tuple[str, ...]
    started_at: str | None
    completed_at: str | None
    completed_reason: OnboardingCompletedReason | None

    @property
    def completed(self) -> bool:
        return self.completed_at is not None


def _keys(value: object) -> tuple[str, ...]:
    return tuple(str(key) for key in value) if isinstance(value, list) else ()


def parse_onboarding(stored: object) -> OnboardingState | None:
    if not isinstance(stored, dict):
        return None
    step_ts = stored.get("step_ts")
    reason = stored.get("completed_reason")
    return OnboardingState(
        channel=stored.get("channel") or None,
        root_ts=stored.get("root_ts") or None,
        progress=stored.get("progress") or None,
        step_ts={str(key): str(ts) for key, ts in step_ts.items()} if isinstance(step_ts, dict) else {},
        summarized=_keys(stored.get("summarized")),
        skipped=_keys(stored.get("skipped")),
        started_at=stored.get("started_at") or None,
        completed_at=stored.get("completed_at") or None,
        completed_reason=reason if reason in ("finished", "nothing_to_set_up", "legacy") else None,
    )


def resolve_onboarding(slack_workspace_id: str, slack_user_id: str) -> OnboardingState | None:
    from products.slack_app.backend.models import SlackSettings

    stored = (
        SlackSettings.objects.filter(slack_workspace_id=slack_workspace_id, slack_user_id=slack_user_id)
        .values_list("onboarding", flat=True)
        .first()
    )
    return parse_onboarding(stored)


def _append_key(card: dict, field: str, key: str) -> None:
    card[field] = [*(existing for existing in card.get(field) or [] if existing != key), key]


def update_onboarding(
    slack_workspace_id: str,
    slack_user_id: str,
    *,
    start: bool = False,
    root: tuple[str, str] | None = None,
    progress: str | None = None,
    step_ts: tuple[str, str] | None = None,
    summarized_step: str | None = None,
    skip_step: str | None = None,
    completed_reason: OnboardingCompletedReason | None = None,
) -> None:
    """``root`` is (channel, ts) and ``step_ts`` is (step key, ts). The row lock stops a skip click and a
    workflow write from losing each other's change."""
    from products.slack_app.backend.models import SlackSettings

    now = timezone.now().isoformat()
    with transaction.atomic():
        row, _ = SlackSettings.objects.select_for_update().get_or_create(
            slack_workspace_id=slack_workspace_id, slack_user_id=slack_user_id
        )
        card = dict(row.onboarding) if isinstance(row.onboarding, dict) else {}
        if start:
            card.setdefault("started_at", now)
            card.setdefault("version", ONBOARDING_VERSION)
        if root is not None:
            card["channel"], card["root_ts"] = root
        if progress is not None:
            card["progress"] = progress
        if step_ts is not None:
            card["step_ts"] = {**(card.get("step_ts") or {}), step_ts[0]: step_ts[1]}
        if summarized_step is not None:
            _append_key(card, "summarized", summarized_step)
        if skip_step is not None:
            _append_key(card, "skipped", skip_step)
        if completed_reason is not None:
            card["completed_at"], card["completed_reason"] = now, completed_reason
        row.onboarding = card
        row.save(update_fields=["onboarding", "updated_at"])


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
    "ONBOARDING_VERSION",
    "OnboardingState",
    "parse_onboarding",
    "has_chosen_untagged_followup_mode",
    "resolve_onboarding",
    "update_onboarding",
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
