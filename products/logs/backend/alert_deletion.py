"""Deletes a logs alert, for every route that deletes one."""

from uuid import UUID

from django.db import transaction

from products.alerts.backend.facade.destinations import soft_delete_all_alert_destinations
from products.alerts_platform.backend.facade.api import close_owned_firings_now
from products.alerts_platform.backend.facade.contracts import PlatformAlertNotEditable
from products.logs.backend.alert_destinations import LOGS_ALERT_EVENT_IDS
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_ownership import before_delete, on_deleted


def delete_alert(*, team_id: int, alert_id: UUID, only_platform_owned: bool = False) -> bool:
    """Deletes the alert, its destinations and its platform copy, whichever stack owns it. False when it was already gone.

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
        if not on_deleted(team_id=locked.team_id, alert_id=locked.id):
            remove_alert_destinations(team_id=locked.team_id, alert_id=locked.id)
        locked.delete()
    return True


def delete_platform_owned(*, team_id: int, legacy_configuration_id: UUID) -> None:
    """Deletes a logs alert through the platform API, its copy, its destinations and its logs row if one
    exists, as the logs API does."""
    alert = LogsAlertConfiguration.objects.filter(id=legacy_configuration_id).first()
    if alert is None:
        # The platform alone deletes a copy whose logs row is already gone. The resolve goes out
        # before the copy's delete removes the destinations it is sent to.
        close_owned_firings_now(team_id=team_id, legacy_configuration_id=legacy_configuration_id)
        on_deleted(team_id=team_id, alert_id=legacy_configuration_id)
        return
    if alert.team_id != team_id:
        # A copy lives on the project, and its logs row on the environment. The platform API checked
        # access to the project only.
        raise PlatformAlertNotEditable(
            "This alert belongs to one of this project's environments. Delete it on that environment's logs alerts page."
        )
    delete_alert(team_id=team_id, alert_id=alert.id, only_platform_owned=True)


def remove_alert_destinations(*, team_id: int, alert_id: UUID) -> None:
    """Removes the HogFunction destinations of a logs alert, which match on its public id."""
    soft_delete_all_alert_destinations(team_id=team_id, alert_id=str(alert_id), allowed_event_ids=LOGS_ALERT_EVENT_IDS)


def _require_platform_owned(alert: LogsAlertConfiguration) -> None:
    if not alert.platform_owned:
        raise PlatformAlertNotEditable("This alert is managed by the logs product. Delete it there.")
