"""CRUD and validation for error tracking alert configurations."""

from typing import Any, Optional
from uuid import UUID

from django.db.models import QuerySet

from posthog.models.integration import Integration
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.user import User

from products.error_tracking.backend.models import ErrorTrackingAlert


class AlertValidationError(Exception):
    pass


def list_alerts(team_id: int) -> QuerySet[ErrorTrackingAlert]:
    return ErrorTrackingAlert.objects.for_team(team_id).order_by("-created_at")


def _parse_alert_id(alert_id: UUID | str) -> Optional[UUID]:
    if isinstance(alert_id, UUID):
        return alert_id
    try:
        return UUID(str(alert_id))
    except ValueError:
        return None


def get_alert(team_id: int, alert_id: UUID | str) -> Optional[ErrorTrackingAlert]:
    parsed_id = _parse_alert_id(alert_id)
    if parsed_id is None:
        return None
    return ErrorTrackingAlert.objects.for_team(team_id).filter(id=parsed_id).first()


def create_alert(
    team_id: int,
    *,
    name: str,
    triggers: list[str],
    channel_type: str,
    integration_id: Optional[int],
    config: dict[str, Any],
    created_by: Optional[User],
) -> ErrorTrackingAlert:
    # Canonicalize up front so validation, the stored row, and the scoped read
    # paths (for_team) all agree on the same team id for child environments.
    team_id = resolve_effective_team_id(team_id)
    _validate_channel(team_id, channel_type=channel_type, integration_id=integration_id, config=config)
    return ErrorTrackingAlert.objects.for_team(team_id, canonical=True).create(
        team_id=team_id,
        name=name,
        triggers=triggers,
        channel_type=channel_type,
        integration_id=integration_id,
        config=config,
        created_by=created_by,
    )


def update_alert(
    team_id: int,
    alert_id: UUID | str,
    *,
    name: Optional[str] = None,
    enabled: Optional[bool] = None,
    triggers: Optional[list[str]] = None,
    config: Optional[dict[str, Any]] = None,
) -> Optional[ErrorTrackingAlert]:
    alert = get_alert(team_id, alert_id)
    if alert is None:
        return None
    if name is not None:
        alert.name = name
    if enabled is not None:
        alert.enabled = enabled
    if triggers is not None:
        alert.triggers = triggers
    if config is not None:
        # Validate against the stored (canonical) team id, not the raw caller id.
        _validate_channel(
            alert.team_id, channel_type=alert.channel_type, integration_id=alert.integration_id, config=config
        )
        alert.config = config
    alert.save()
    return alert


def delete_alert(team_id: int, alert_id: UUID | str) -> bool:
    parsed_id = _parse_alert_id(alert_id)
    if parsed_id is None:
        return False
    deleted, _ = ErrorTrackingAlert.objects.for_team(team_id).filter(id=parsed_id).delete()
    return deleted > 0


def _validate_channel(
    team_id: int, *, channel_type: str, integration_id: Optional[int], config: dict[str, Any]
) -> None:
    if not isinstance(config, dict):
        raise AlertValidationError("Alert config must be an object.")
    if channel_type == ErrorTrackingAlert.ChannelType.SLACK:
        if integration_id is None:
            raise AlertValidationError("Slack alerts require an integration.")
        if not Integration.objects.filter(
            team_id=team_id, id=integration_id, kind=Integration.IntegrationKind.SLACK
        ).exists():
            raise AlertValidationError("Slack integration not found for this project.")
        if not config.get("channel"):
            raise AlertValidationError("Slack alerts require a channel in the config.")
