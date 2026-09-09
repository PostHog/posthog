"""CRUD and validation for error tracking alert configurations."""

from typing import Any, Optional
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet

import structlog

from posthog.cdp.filters import compile_filters_bytecode
from posthog.models.integration import Integration
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false

from products.error_tracking.backend.models import ErrorTrackingAlert, ErrorTrackingAlertDestination

logger = structlog.get_logger(__name__)

NATIVE_ALERTS_FLAG = "error-tracking-native-alerts"


def native_alerts_enabled(team_id: int) -> bool:
    try:
        # Alert rows are canonical-project-scoped, so the flag must bucket child
        # environments with their parent or per-environment ids would gate
        # differently than the rows they read.
        team_id = resolve_effective_team_id(team_id)
        return feature_enabled_or_false(
            NATIVE_ALERTS_FLAG,
            str(team_id),
            groups={"project": str(team_id)},
            group_properties={"project": {"id": str(team_id)}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception:
        # An unreleased feature stays off when the flags service is unreachable,
        # rather than defaulting on or failing the caller.
        logger.exception("error_tracking_native_alerts_flag_check_failed", team_id=team_id)
        return False


class AlertValidationError(Exception):
    pass


def list_alerts(team_id: int) -> QuerySet[ErrorTrackingAlert]:
    return ErrorTrackingAlert.objects.for_team(team_id).prefetch_related("destinations").order_by("-created_at")


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
    return ErrorTrackingAlert.objects.for_team(team_id).prefetch_related("destinations").filter(id=parsed_id).first()


def create_alert(
    team_id: int,
    *,
    name: str,
    triggers: list[str],
    filters: dict[str, Any],
    throttle_seconds: int,
    destinations: list[dict[str, Any]],
    created_by: Optional[User],
) -> ErrorTrackingAlert:
    # Canonicalize up front so validation, the stored row, and the scoped read
    # paths (for_team) all agree on the same team id for child environments.
    team_id = resolve_effective_team_id(team_id)
    compiled_filters = _compile_filters(team_id, filters)
    _reject_duplicate_destinations(destinations)
    for destination in destinations:
        _validate_destination(team_id, destination)

    with transaction.atomic():
        alert = ErrorTrackingAlert.objects.for_team(team_id, canonical=True).create(
            team_id=team_id,
            name=name,
            triggers=triggers,
            filters=compiled_filters,
            throttle_seconds=throttle_seconds,
            created_by=created_by,
        )
        for destination in destinations:
            ErrorTrackingAlertDestination.objects.for_team(team_id, canonical=True).create(
                team_id=team_id,
                alert=alert,
                channel_type=destination["channel_type"],
                integration_id=destination["integration_id"],
                config=destination["config"],
            )
    # Refetch with destinations prefetched so the caller serializes one consistent shape.
    return ErrorTrackingAlert.objects.for_team(team_id).prefetch_related("destinations").get(id=alert.id)


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
) -> Optional[ErrorTrackingAlert]:
    parsed_id = _parse_alert_id(alert_id)
    if parsed_id is None:
        return None

    updates = (name, enabled, triggers, filters, throttle_seconds, destinations)
    if all(value is None for value in updates):
        # Nothing to change; skip the write so updated_at stays untouched.
        return get_alert(team_id, parsed_id)

    if destinations is not None:
        _reject_duplicate_destinations(destinations)

    with transaction.atomic():
        # Lock the row so concurrent partial updates cannot overwrite each other's fields.
        alert = ErrorTrackingAlert.objects.for_team(team_id).select_for_update().filter(id=parsed_id).first()
        if alert is None:
            return None
        if name is not None:
            alert.name = name
        if enabled is not None:
            alert.enabled = enabled
        if triggers is not None:
            alert.triggers = triggers
        if filters is not None:
            # Validate against the stored (canonical) team id, not the raw caller id.
            alert.filters = _compile_filters(alert.team_id, filters)
        if throttle_seconds is not None:
            alert.throttle_seconds = throttle_seconds
        if destinations is not None:
            for destination in destinations:
                _validate_destination(alert.team_id, destination)

        alert.save()
        if destinations is not None:
            # Destinations are replaced wholesale: threads cascade with removed rows,
            # so a repointed channel starts a fresh conversation (per the alerting RFC).
            alert.destinations.all().delete()
            for destination in destinations:
                ErrorTrackingAlertDestination.objects.for_team(alert.team_id, canonical=True).create(
                    team_id=alert.team_id,
                    alert=alert,
                    channel_type=destination["channel_type"],
                    integration_id=destination["integration_id"],
                    config=destination["config"],
                )
    return get_alert(team_id, alert.id)


def delete_alert(team_id: int, alert_id: UUID | str) -> bool:
    parsed_id = _parse_alert_id(alert_id)
    if parsed_id is None:
        return False
    deleted, _ = ErrorTrackingAlert.objects.for_team(team_id).filter(id=parsed_id).delete()
    return deleted > 0


def _compile_filters(team_id: int, filters: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(filters, dict):
        raise AlertValidationError("Alert filters must be an object.")
    team = Team.objects.get(id=team_id)
    compiled = compile_filters_bytecode(dict(filters), team)
    if compiled.get("bytecode_error"):
        raise AlertValidationError(f"Invalid filter configuration: {compiled['bytecode_error']}")
    return compiled


def _reject_duplicate_destinations(destinations: list[dict[str, Any]]) -> None:
    # Delivery fans out one notification per destination row, so two destinations
    # pointing at the same channel would double-post every notification. The
    # identity ignores display-only config keys such as channel_name on purpose.
    seen = set()
    for destination in destinations:
        config = destination.get("config")
        channel = config.get("channel") if isinstance(config, dict) else None
        key = (destination.get("channel_type"), destination.get("integration_id"), channel)
        if key in seen:
            raise AlertValidationError("Duplicate destinations are not allowed.")
        seen.add(key)


def _validate_destination(team_id: int, destination: dict[str, Any]) -> None:
    channel_type = destination.get("channel_type")
    integration_id = destination.get("integration_id")
    config = destination.get("config")
    if not isinstance(config, dict):
        raise AlertValidationError("Destination config must be an object.")
    if channel_type == ErrorTrackingAlertDestination.ChannelType.SLACK:
        if integration_id is None:
            raise AlertValidationError("Slack destinations require an integration.")
        # Integrations are stored on environment teams while alert rows live on the
        # canonical team, so accept any integration in the same project.
        project_id = Team.objects.values_list("project_id", flat=True).get(id=team_id)
        if not Integration.objects.filter(
            team__project_id=project_id, id=integration_id, kind=Integration.IntegrationKind.SLACK
        ).exists():
            raise AlertValidationError("Slack integration not found for this project.")
        channel = config.get("channel")
        if not isinstance(channel, str) or not channel:
            raise AlertValidationError("Slack destinations require a channel id string in the config.")
    else:
        raise AlertValidationError(f"Unsupported destination channel type: {channel_type}")
