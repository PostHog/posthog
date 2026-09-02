"""Activity-log hooks for SignalScoutConfig and SignalTeamConfig changes.

`ModelActivityMixin.save()` only *emits* `model_activity_signal` — it does not persist
anything. These receivers are the consumers that turn the emitted signal into a stored
`ActivityLog` row. Without them, nothing about either model would ever appear in the
activity log. Imported from `SignalsConfig.ready()` so they register at startup.
"""

import dataclasses
from typing import Any

import structlog

from posthog.models.activity_logging.activity_log import (
    ActivityContextBase,
    ActivityScope,
    Detail,
    changes_between,
    log_activity,
)
from posthog.models.activity_logging.model_activity import get_current_trigger
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.user import User

from .models import SignalScoutConfig, SignalTeamConfig

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class SignalScoutConfigContext(ActivityContextBase):
    skill_name: str


@mutable_receiver(model_activity_signal, sender=SignalScoutConfig)
def handle_signal_scout_config_change(
    sender: type[SignalScoutConfig],
    scope: ActivityScope,
    before_update: SignalScoutConfig | None,
    after_update: SignalScoutConfig | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    instance: SignalScoutConfig | None = after_update or before_update
    if instance is None:
        return

    log_activity(
        organization_id=None,
        team_id=instance.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=instance.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=instance.skill_name,
            # Set by system-driven saves (the inactivity sweep) so an entry with no user reads as
            # "this job did it" rather than as an unattributed edit.
            trigger=get_current_trigger(),
            context=SignalScoutConfigContext(skill_name=instance.skill_name),
        ),
    )


@mutable_receiver(model_activity_signal, sender=SignalTeamConfig)
def handle_signal_team_config_change(
    sender: type[SignalTeamConfig],
    scope: ActivityScope,
    before_update: SignalTeamConfig | None,
    after_update: SignalTeamConfig | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    instance: SignalTeamConfig | None = after_update or before_update
    if instance is None:
        return

    # On create, diff against a fresh default row rather than None. `changes_between` yields
    # nothing when `previous` is None, which would drop the create branch of update_or_create() —
    # the path Slack onboarding takes to set a channel on a team whose row was never materialized.
    # Diffing against defaults keeps an all-default create (team creation, lazy read) silent while
    # still auditing a create that carries a non-default value.
    previous = before_update if before_update is not None else SignalTeamConfig()
    changes = changes_between(scope, previous=previous, current=after_update)
    # Only persist saves that moved a field, which also keeps idempotent re-saves out of the log.
    if not changes:
        return

    log_activity(
        organization_id=None,
        team_id=instance.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=instance.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes,
            # Singleton per team, so there's no per-row name to show; label it where a reader
            # would go to find the setting instead of exposing the model name.
            name="Inbox settings",
            trigger=get_current_trigger(),
        ),
    )
