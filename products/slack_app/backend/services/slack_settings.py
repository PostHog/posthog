"""Read helpers for per-(Slack workspace, Slack user) settings backed by
`models.SlackSettings` (today: the untagged follow-up mode), plus the shared
AI-triple value object.

Model preferences themselves live in the central tasks config
(`products.tasks.backend.facade.ai_run_defaults`); `AIPreferences` keeps the
task-run serializer's field names so resolver output can be handed to the task
layer with zero translation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from products.slack_app.backend.models import UntaggedFollowupMode

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
    reply in the threads they started. An absent row, an empty column, or a
    value we no longer recognise all resolve to `NEVER`: the feature is opt-in,
    so nothing is picked up until someone asks for it.
    """

    if not slack_user_id:
        return UntaggedFollowupMode.NEVER

    from products.slack_app.backend.models import SlackSettings

    row = (
        SlackSettings.objects.filter(
            slack_workspace_id=integration.integration_id,
            slack_user_id=slack_user_id,
        )
        .values("untagged_followup_mode")
        .first()
    )
    stored = row["untagged_followup_mode"] if row else None
    if stored in UntaggedFollowupMode.values:
        return UntaggedFollowupMode(stored)
    return UntaggedFollowupMode.NEVER


__all__ = [
    "AIPreferences",
    "resolve_untagged_followup_mode",
]
