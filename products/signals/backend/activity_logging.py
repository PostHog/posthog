"""Activity-log hook for SignalScoutConfig create/update/delete.

`ModelActivityMixin.save()` only *emits* `model_activity_signal` — it does not persist
anything. This receiver is the consumer that turns the emitted signal into a stored
`ActivityLog` row. Without it, nothing about SignalScoutConfig would ever appear in the
activity log. Imported from `SignalsConfig.ready()` so it registers at startup.
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
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.user import User

from .models import SignalScoutConfig

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
            context=SignalScoutConfigContext(skill_name=instance.skill_name),
        ),
    )
