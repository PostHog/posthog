"""CRUD and validation for error tracking alert configurations."""

import json
from typing import Any, Optional
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet

import structlog

from posthog.cdp.filters import compile_filters_bytecode
from posthog.dataclasses import frozen
from posthog.models.integration import Integration
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false

from products.error_tracking.backend.models import (
    ErrorTrackingAlert,
    ErrorTrackingAlertDestination,
    ErrorTrackingAlertThread,
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
)

logger = structlog.get_logger(__name__)

NATIVE_ALERTS_FLAG = "error-tracking-native-alerts"

# Longest throttle window an alert may configure. Per-issue throttle claims live in
# shared Redis for exactly this long, so the API and delivery must agree on it.
MAX_THROTTLE_SECONDS = 30 * 24 * 60 * 60


def native_alerts_enabled(team_id: int) -> bool:
    # Flags forced on for the whole instance (dev, self-hosted) reach the frontend
    # through the persisted list, so the API must honor the same baseline.
    if NATIVE_ALERTS_FLAG in settings.PERSISTED_FEATURE_FLAGS:
        return True
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
            _reconcile_destinations(alert, destinations)
    return get_alert(team_id, alert.id)


@frozen
class _DestinationKey:
    """Identity of a destination row: same channel on the same integration means the same row."""

    channel_type: str
    integration_id: int | None
    channel: str | None


def _destination_key(channel_type: str, integration_id: Any, config: dict[str, Any]) -> _DestinationKey:
    return _DestinationKey(channel_type=channel_type, integration_id=integration_id, channel=config.get("channel"))


def _reconcile_destinations(alert: ErrorTrackingAlert, destinations: list[dict[str, Any]]) -> None:
    # A destination that still points at the same channel keeps its row, so its open
    # threads and delivery history survive an edit to the alert's other fields. Only a
    # removed or repointed channel drops its row, and its threads cascade with it so the
    # new channel starts a fresh conversation.
    existing = {
        _destination_key(row.channel_type, row.integration_id, row.config): row
        for row in ErrorTrackingAlertDestination.objects.for_team(alert.team_id, canonical=True).filter(alert=alert)
    }
    wanted = {_destination_key(d["channel_type"], d["integration_id"], d["config"]): d for d in destinations}
    for key, row in existing.items():
        if key not in wanted:
            row.delete()
    for key, destination in wanted.items():
        current = existing.get(key)
        if current is None:
            ErrorTrackingAlertDestination.objects.for_team(alert.team_id, canonical=True).create(
                team_id=alert.team_id,
                alert=alert,
                channel_type=destination["channel_type"],
                integration_id=destination["integration_id"],
                config=destination["config"],
            )
        elif current.config != destination["config"]:
            current.config = destination["config"]
            current.save(update_fields=["config", "updated_at"])


def delete_alert(team_id: int, alert_id: UUID | str) -> bool:
    parsed_id = _parse_alert_id(alert_id)
    if parsed_id is None:
        return False
    deleted, _ = ErrorTrackingAlert.objects.for_team(team_id).filter(id=parsed_id).delete()
    return deleted > 0


# Issue fields the delivery globals carry on every lifecycle event, so an issue-level
# leaf compiles to `properties.<key>` exactly like the taxonomy's Issues group emits it.
ISSUE_FILTER_KEYS = frozenset({"name", "issue_description", "severity", "first_seen", "assignee"})


# The issue page stores description filters under `issue_description`; the same field
# reaches the event namespace as `description`.
_ISSUE_KEY_IN_EVENT_NAMESPACE = {"issue_description": "description"}


def _validate_issue_leaf(property_filter: dict[str, Any]) -> None:
    key = property_filter["key"]
    if key not in ISSUE_FILTER_KEYS:
        raise AlertValidationError(f"Unknown issue property in alert filters: {key}.")
    if key != "assignee" or property_filter.get("operator") in ("is_set", "is_not_set"):
        return
    # The assignee picker stores the JSON string "null" when its selection is cleared;
    # no issue ever carries that value, so the filter would never match.
    values = property_filter.get("value")
    for value in values if isinstance(values, list) else [values]:
        try:
            parsed = json.loads(value) if isinstance(value, str) else None
        except ValueError:
            parsed = None
        if not isinstance(parsed, dict) or "id" not in parsed:
            raise AlertValidationError("Choose an assignee for the assignee filter, or remove it.")


def _validate_filter_surface(filters: dict[str, Any]) -> None:
    # Delivery evaluates filters without person, group, or cohort context, and
    # native alerts have no bytecode refresh when actions or test-account
    # definitions change. Reject what cannot be honored instead of silently
    # mis-evaluating it.
    unsupported_keys = [key for key in ("actions", "filter_test_accounts") if filters.get(key)]
    if unsupported_keys:
        raise AlertValidationError(f"Alert filters do not support {', '.join(unsupported_keys)}.")
    property_lists = [filters.get("properties") or []]
    for entity in filters.get("events") or []:
        if isinstance(entity, dict):
            if entity.get("type") != "events":
                # A typeless entity compiles without its event-name predicate (a
                # match-all branch), and an action entity smuggled into the events
                # list would compile too.
                raise AlertValidationError(f"Alert event filters must have type events, got: {entity.get('type')}.")
            property_lists.append(entity.get("properties") or [])
    issue_keys: set[str] = set()
    event_keys: set[str] = set()
    for property_list in property_lists:
        # The compiler accepts an object here and iterating it would only yield keys,
        # so the leaf checks below would never run.
        if not isinstance(property_list, list):
            raise AlertValidationError("Alert property filters must be a list.")
        for property_filter in property_list:
            # A leaf without a key makes the compiler fall back to a constant-true
            # branch, turning a "filtered" alert into a match-all.
            if not isinstance(property_filter, dict) or not isinstance(property_filter.get("key"), str):
                raise AlertValidationError("Each alert property filter must be an object with a key.")
            property_type = property_filter.get("type")
            if property_type == "error_tracking_issue":
                _validate_issue_leaf(property_filter)
                issue_keys.add(_ISSUE_KEY_IN_EVENT_NAMESPACE.get(property_filter["key"], property_filter["key"]))
            elif property_type in (None, "event"):
                event_keys.add(property_filter["key"])
            else:
                raise AlertValidationError(
                    f"Alert filters support event and issue properties only, got: {property_type}."
                )
    # Both kinds evaluate under one property namespace, so one alert cannot ask for the
    # issue's value and the exception's value of the same field.
    if issue_keys & event_keys:
        raise AlertValidationError(
            f"Filter on {', '.join(sorted(issue_keys & event_keys))} as an issue property or an exception property, not both."
        )


def _compile_filters(team_id: int, filters: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(filters, dict):
        raise AlertValidationError("Alert filters must be an object.")
    _validate_filter_surface(filters)
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
        if not isinstance(config.get("reply_broadcast", False), bool):
            raise AlertValidationError("reply_broadcast must be a boolean.")
    else:
        raise AlertValidationError(f"Unsupported destination channel type: {channel_type}")


PREVIEW_REPLY_EVENTS = ("$error_tracking_issue_assigned", "$error_tracking_issue_resolved")


def preview_alert_messages(
    team_id: int, trigger: str, actor_email: str | None, *, sample_team_id: int | None = None
) -> dict[str, Any]:
    """Render the Slack thread an alert would open for the team's most recent issue.

    Returns the root for the trigger's opener event, then the replies and root edit a
    typical lifecycle produces, so the editor can show the thread model on real data.
    Returns the raw builder output; the facade shapes it into the contract.
    """
    # The temporal package aggregator loads every worker-only workflow module; keep it
    # off the web import path.
    from products.error_tracking.backend.temporal.alerts.delivery import OPENER_TRIGGERS  # noqa: PLC0415
    from products.error_tracking.backend.temporal.alerts.messages import (  # noqa: PLC0415
        build_reply_text,
        build_root_edit,
        build_root_message,
    )
    from products.error_tracking.backend.temporal.alerts.types import AlertDeliveryWorkflowInputs  # noqa: PLC0415

    events_by_trigger = {str(value): event for event, value in OPENER_TRIGGERS.items()}
    if trigger not in events_by_trigger:
        raise AlertValidationError(f"Unknown trigger: {trigger}")
    opener_event = events_by_trigger[trigger]

    # The sample comes from one environment the caller is authorized on (the view checks
    # the requested one): access control is per environment, so a sibling's issue must not
    # leak through a project-wide pick. Issue ids are time-ordered UUIDs, so the primary key
    # stands in for a created_at sort the table has no composite index for.
    issue = ErrorTrackingIssue.objects.filter(team_id=sample_team_id or team_id).order_by("-id").first()
    fingerprint = (
        ErrorTrackingIssueFingerprintV2.objects.filter(team_id=issue.team_id, issue_id=issue.id)
        .values_list("fingerprint", flat=True)
        .first()
        if issue is not None
        else None
    )

    def inputs(event: str, **overrides: Any) -> AlertDeliveryWorkflowInputs:
        base: dict[str, Any] = {
            "notification_id": "preview",
            # The View issue link carries the environment, so a sampled issue links to its own.
            "team_id": issue.team_id if issue is not None else team_id,
            "issue_id": str(issue.id) if issue is not None else "preview",
            "event": event,
            "issue_name": issue.name if issue is not None else "TypeError: Cannot read properties of undefined",
            "issue_description": issue.description
            if issue is not None
            else "at CheckoutForm.submit (checkout.tsx:142)",
            "status": "Active",
            "actor_email": actor_email,
            "severity": issue.severity if issue is not None else None,
            "fingerprint": fingerprint,
        }
        if event == "$error_tracking_issue_spiking":
            base["extra"] = {"current_bucket_value": "600", "computed_baseline": "12.5"}
        base.update(overrides)
        return AlertDeliveryWorkflowInputs(**base)

    root = build_root_message(inputs(opener_event))
    messages: list[dict[str, Any]] = [
        {"kind": "root", "event": opener_event, "text": root["text"], "blocks": root["blocks"]}
    ]
    for event in PREVIEW_REPLY_EVENTS:
        status = "Resolved" if event == "$error_tracking_issue_resolved" else "Active"
        reply = build_reply_text(inputs(event, status=status))
        if reply is not None:
            messages.append({"kind": "reply", "event": event, "text": reply, "blocks": None})
    edit = build_root_edit(inputs("$error_tracking_issue_resolved", status="Resolved"), headline=root["headline"])
    messages.append(
        {"kind": "root_edit", "event": "$error_tracking_issue_resolved", "text": edit["text"], "blocks": edit["blocks"]}
    )
    return {"issue_id": issue.id if issue is not None else None, "messages": messages}


def list_issue_threads(team_id: int, issue_id: UUID | str) -> QuerySet[ErrorTrackingAlertThread]:
    parsed_id = _parse_alert_id(issue_id)
    if parsed_id is None:
        return ErrorTrackingAlertThread.objects.none()
    return (
        ErrorTrackingAlertThread.objects.for_team(team_id)
        .filter(issue_id=parsed_id)
        .select_related("alert", "destination", "destination__integration")
        .order_by("-created_at")
    )


def slack_thread_url(external_ref: dict[str, Any], workspace_id: str | None) -> str | None:
    channel = external_ref.get("channel")
    ts = external_ref.get("ts")
    if not channel or not ts:
        return None
    if workspace_id:
        # Workspace-qualified deep link, so someone signed into several workspaces lands
        # in the right one; the bare archive link resolves through their default.
        return f"https://app.slack.com/client/{workspace_id}/{channel}/thread/{channel}-{ts}"
    return f"https://slack.com/archives/{channel}/p{str(ts).replace('.', '')}"
