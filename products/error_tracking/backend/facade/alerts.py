"""Facade for error tracking native alert configurations."""

from typing import Any, Optional
from uuid import UUID

from posthog.models.user import User

from ..logic import alerts as _alerts
from ..models import ErrorTrackingAlert as ErrorTrackingAlertModel
from . import contracts

AlertValidationError = _alerts.AlertValidationError

NATIVE_ALERTS_FLAG = _alerts.NATIVE_ALERTS_FLAG
native_alerts_enabled = _alerts.native_alerts_enabled


def _to_alert(alert: ErrorTrackingAlertModel) -> contracts.ErrorTrackingAlert:
    return contracts.ErrorTrackingAlert(
        id=alert.id,
        name=alert.name,
        enabled=alert.enabled,
        triggers=list(alert.triggers),
        filters=dict(alert.filters),
        throttle_seconds=alert.throttle_seconds,
        destinations=[
            contracts.ErrorTrackingAlertDestination(
                id=destination.id,
                channel_type=destination.channel_type,
                integration_id=destination.integration_id,
                config=dict(destination.config),
                created_at=destination.created_at,
                updated_at=destination.updated_at,
            )
            for destination in alert.destinations.all()
        ],
        created_at=alert.created_at,
        updated_at=alert.updated_at,
    )


def list_alerts(team_id: int) -> list[contracts.ErrorTrackingAlert]:
    return [_to_alert(alert) for alert in _alerts.list_alerts(team_id)]


def get_alert(team_id: int, alert_id: UUID | str) -> Optional[contracts.ErrorTrackingAlert]:
    alert = _alerts.get_alert(team_id, alert_id)
    return _to_alert(alert) if alert is not None else None


def create_alert(
    team_id: int,
    *,
    name: str,
    triggers: list[str],
    filters: dict[str, Any],
    throttle_seconds: int,
    destinations: list[dict[str, Any]],
    created_by: Optional[User],
) -> contracts.ErrorTrackingAlert:
    return _to_alert(
        _alerts.create_alert(
            team_id,
            name=name,
            triggers=triggers,
            filters=filters,
            throttle_seconds=throttle_seconds,
            destinations=destinations,
            created_by=created_by,
        )
    )


def update_alert(
    team_id: int,
    alert_id: UUID | str,
    *,
    name: Optional[str] = None,
    enabled: Optional[bool] = None,
    triggers: Optional[list[str]] = None,
    filters: Optional[dict[str, Any]] = None,
    throttle_seconds: Optional[int] = None,
    destinations: Optional[list[dict[str, Any]]] = None,
) -> Optional[contracts.ErrorTrackingAlert]:
    alert = _alerts.update_alert(
        team_id,
        alert_id,
        name=name,
        enabled=enabled,
        triggers=triggers,
        filters=filters,
        throttle_seconds=throttle_seconds,
        destinations=destinations,
    )
    return _to_alert(alert) if alert is not None else None


def delete_alert(team_id: int, alert_id: UUID | str) -> bool:
    return _alerts.delete_alert(team_id, alert_id)
