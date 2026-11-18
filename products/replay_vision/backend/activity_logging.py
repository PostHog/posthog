"""Activity-log receivers for Replay Vision's user-configured models.

Lives here, not in the viewsets, so it connects at `AppConfig.ready()` in every process. Scanners and
alerts are written from Temporal workers and management commands as well as from the API, and an audit
trail that only covers web requests is worse than none: it reads as "nobody changed this".
"""

from typing import TYPE_CHECKING, Any

from posthog.models.activity_logging.activity_log import AuditableScope, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver

from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerOrigin
from products.replay_vision.backend.models.vision_alert import VisionAlertConfiguration

if TYPE_CHECKING:
    from posthog.models.user import User

AuditedModel = ReplayScanner | VisionAlertConfiguration


def _log(
    *,
    scope: AuditableScope,
    before_update: AuditedModel | None,
    after_update: AuditedModel | None,
    activity: str,
    user: "User | None",
    was_impersonated: bool,
) -> None:
    instance = after_update or before_update
    if instance is None:
        return
    log_activity(
        organization_id=instance.team.organization_id,
        team_id=instance.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=instance.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            name=instance.name,
            changes=changes_between(scope, previous=before_update, current=after_update),
        ),
    )


@mutable_receiver(model_activity_signal, sender=ReplayScanner)
def handle_replay_scanner_change(
    sender: type[ReplayScanner],
    scope: AuditableScope,
    before_update: ReplayScanner | None,
    after_update: ReplayScanner | None,
    activity: str,
    user: "User | None" = None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    instance = after_update or before_update
    # Inline scanners are minted per one-off scan, not configured by a person.
    if instance is None or instance.origin != ScannerOrigin.CONFIGURED:
        return

    _log(
        scope=scope,
        before_update=before_update,
        after_update=after_update,
        activity=activity,
        user=user,
        was_impersonated=was_impersonated,
    )


@mutable_receiver(model_activity_signal, sender=VisionAlertConfiguration)
def handle_vision_alert_change(
    sender: type[VisionAlertConfiguration],
    scope: AuditableScope,
    before_update: VisionAlertConfiguration | None,
    after_update: VisionAlertConfiguration | None,
    activity: str,
    user: "User | None" = None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    _log(
        scope=scope,
        before_update=before_update,
        after_update=after_update,
        activity=activity,
        user=user,
        was_impersonated=was_impersonated,
    )
