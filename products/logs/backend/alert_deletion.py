"""Deletes a logs alert, for every route that deletes one."""

from uuid import UUID

from django.db import transaction

from products.alerts.backend.facade.destinations import soft_delete_all_alert_destinations
from products.alerts_platform.backend.facade.contracts import PlatformAlertNotEditable
from products.logs.backend.alert_destinations import LOGS_ALERT_EVENT_IDS
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_ownership import before_delete, on_deleted


def delete_alert(*, team_id: int, alert_id: UUID, only_platform_owned: bool = False) -> bool:
    """Deletes the alert, its destinations and any platform copy. False when it was already gone.

    With `only_platform_owned`, raises `PlatformAlertNotEditable` when the alert is not, or stops
    being, owned by the platform, such as after a rollback hands it back mid-delete.
    """
    alert = LogsAlertConfiguration.objects.filter(team_id=team_id, id=alert_id).first()
    if alert is None:
        return False
    if only_platform_owned:
        _require_platform_owned(alert)
    # Before the transaction, so the resolve is sent while the destinations it goes to still exist.
    before_delete(alert)
    with transaction.atomic():
        locked = LogsAlertConfiguration.objects.select_for_update().filter(team_id=team_id, id=alert_id).first()
        if locked is None:
            return False
        if only_platform_owned:
            # Checked again under the lock, because the cutover and rollback commands take the same lock.
            _require_platform_owned(locked)
        soft_delete_all_alert_destinations(
            team_id=locked.team_id, alert_id=str(locked.id), allowed_event_ids=LOGS_ALERT_EVENT_IDS
        )
        if locked.platform_owned:
            on_deleted(team_id=locked.team_id, alert_id=locked.id)
        locked.delete()
    return True


def delete_platform_owned(*, team_id: int, legacy_configuration_id: UUID) -> None:
    """Deletes a logs alert through the platform API, both rows and its destinations, as the logs API does."""
    alert = LogsAlertConfiguration.objects.filter(id=legacy_configuration_id).first()
    if alert is None:
        # A copy whose logs row is already gone has nothing left to close or to delete on the logs side.
        on_deleted(team_id=team_id, alert_id=legacy_configuration_id)
        return
    if alert.team_id != team_id:
        # A copy lives on the project, and its logs row on the environment. The platform API checked
        # access to the project only.
        raise PlatformAlertNotEditable(
            "This alert belongs to one of this project's environments. Delete it on that environment's logs alerts page."
        )
    delete_alert(team_id=team_id, alert_id=alert.id, only_platform_owned=True)


def _require_platform_owned(alert: LogsAlertConfiguration) -> None:
    if not alert.platform_owned:
        raise PlatformAlertNotEditable("This alert is managed by the logs product. Delete it there.")
