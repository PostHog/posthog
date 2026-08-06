"""Activity-log hooks for SignalScoutConfig and SignalTeamConfig changes.

`ModelActivityMixin.save()` only *emits* `model_activity_signal` — it does not persist
anything. These receivers are the consumers that turn the emitted signal into a stored
`ActivityLog` row. Without them, nothing about either config would ever appear in the
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
    # Every team gets a row with default settings, created by a post_save receiver on Team (or
    # lazily on first read). Nobody chose those defaults, so a `created` entry would be noise in
    # every new project's activity log — only the later edits are decisions worth recording.
    if activity != "updated" or after_update is None:
        return

    changes = changes_between(scope, previous=before_update, current=after_update)
    # A PATCH that re-sends the current values still saves. Without this, re-picking the
    # threshold a team already had would read as a change.
    if not changes:
        return

    log_activity(
        organization_id=None,
        team_id=after_update.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes,
            name="inbox settings",
            trigger=get_current_trigger(),
        ),
    )
