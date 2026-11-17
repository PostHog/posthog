"""Evaluation of due error tracking alerts on the shared alerts platform.

Each check reads the issue changes recorded since the previous check, keeps the ones its triggers
and filters match, and reports one firing group per issue. An issue with no new change in a later
check resolves without a message, so the next matching change on it is announced again.

This reads and decides. It writes nothing, so a retried attempt reads the same changes and makes
the same decisions. The platform records the outcomes in its own activity.
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Final

import structlog
from pydantic import ValidationError

from posthog.dataclasses import frozen
from posthog.models import Team

from products.alerts_platform.backend.facade.api import due_checks, slot_of
from products.alerts_platform.backend.facade.check_errors import classify_check_error
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertEventKind,
    InstanceCheckState,
    PlatformAlertCheckInput,
    PlatformAlertOutcome,
    SourceBatchEvaluation,
    SourceKind,
)
from products.alerts_platform.backend.facade.grouping import (
    GroupObservation,
    bounded_grouping_key,
    decide_groups,
    delivery_parts,
    muted_value,
)
from products.alerts_platform.backend.facade.lifecycle import (
    NOTIFICATION_EVENT_KINDS,
    PLATFORM_DEFAULT_ALERT_POLICY,
    AlertSnapshot,
    AlertState,
    CheckInput,
    NotificationAction,
    decide_firing_episode,
    evaluate_alert_check,
)
from products.alerts_platform.backend.facade.payload import MAX_BATCH_PAYLOAD_BYTES, payload_bytes
from products.alerts_platform.backend.facade.scheduling import is_utc_datetime_blocked, parse_blocked_windows_tuples
from products.error_tracking.backend.facade.contracts import LifecycleFilterOutcome
from products.error_tracking.backend.logic.alerts import compile_alert_filters
from products.error_tracking.backend.logic.assignees import assignee_property
from products.error_tracking.backend.models import ErrorTrackingIssueChange
from products.error_tracking.backend.platform_alerts.source_config import (
    ErrorTrackingPlatformAlertConfig,
    ErrorTrackingPlatformAlertTrigger,
)
from products.error_tracking.backend.platform_alerts.wording import (
    ISSUE_ID_LABEL,
    ISSUE_NAME_LABEL,
    TRIGGER_LABEL,
    alert_url,
)
from products.error_tracking.backend.temporal.alerts.filter_evaluation import (
    evaluate_lifecycle_filters,
    filters_are_configured,
)
from products.error_tracking.backend.temporal.alerts.types import AlertDeliveryWorkflowInputs
from products.error_tracking.backend.temporal.lifecycle.event_properties import fetch_event_properties

logger = structlog.get_logger(__name__)

SOURCE: Final = SourceKind.ERROR_TRACKING
# A change is announced when it happens, and an issue with no new change resolves without a message.
POLICY: Final = replace(PLATFORM_DEFAULT_ALERT_POLICY, notify_resolve=False)

# A change row commits after its `created_at`, so a window that ended now would miss a row still in
# its transaction and never read it again.
SETTLE: Final = timedelta(seconds=60)
# How far back a check that ran late reads. Older changes are no longer news.
MAX_WINDOW: Final = timedelta(hours=24)
# Rows one check reads. A check that finds more reports what it read and says the results were cut.
MAX_CHANGES_PER_CHECK: Final = 1_000

EVENT_IDS_BY_KIND: Final[dict[str, str]] = {
    AlertEventKind.FIRING.value: "$error_tracking_alert_firing",
    AlertEventKind.ERRORED.value: "$error_tracking_alert_errored",
    AlertEventKind.BROKEN.value: "$error_tracking_alert_broken",
}

# The internal event each trigger matches, so a filter written for error tracking's destinations
# reads the same event name here.
_TRIGGER_EVENTS: Final[dict[ErrorTrackingPlatformAlertTrigger, str]] = {
    ErrorTrackingPlatformAlertTrigger.ISSUE_CREATED: "$error_tracking_issue_created",
    ErrorTrackingPlatformAlertTrigger.ISSUE_REOPENED: "$error_tracking_issue_reopened",
    ErrorTrackingPlatformAlertTrigger.ISSUE_ASSIGNED: "$error_tracking_issue_assigned",
}
_TRIGGER_KINDS: Final[dict[ErrorTrackingPlatformAlertTrigger, str]] = {
    ErrorTrackingPlatformAlertTrigger.ISSUE_CREATED: ErrorTrackingIssueChange.Kind.CREATED,
    ErrorTrackingPlatformAlertTrigger.ISSUE_REOPENED: ErrorTrackingIssueChange.Kind.STATUS_CHANGED,
    ErrorTrackingPlatformAlertTrigger.ISSUE_ASSIGNED: ErrorTrackingIssueChange.Kind.ASSIGNEE_CHANGED,
}

_INVALID_CONFIG: Final = "The alert's configuration is no longer valid. Edit the alert to fix it."

Decision = tuple[PlatformAlertOutcome, AlertDeliveryRequest | None]


@frozen
class _IssueRef:
    # The fetch falls back to it when the exception's own time cannot be parsed.
    created_at: str


@frozen
class _ExceptionRef:
    """The exception a change came from, as the exception property fetch reads it."""

    team_id: int
    event_uuid: str
    event_timestamp: str
    issue: _IssueRef


def evaluate_error_tracking_alert_batch(team_id: int, slot: str, cutoff: datetime) -> SourceBatchEvaluation:
    """Evaluates one batch key of error tracking alerts against the tick's cutoff."""
    checks = due_checks(team_id, SOURCE.value, slot, cutoff)
    if not checks:
        return SourceBatchEvaluation(outcomes=(), deliveries=())
    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return SourceBatchEvaluation(outcomes=(), deliveries=())
    decided = [_evaluate(team, check, now=cutoff) for check in checks]
    return _collect(decided, team_id=team_id, slot=slot)


def change_window(check: PlatformAlertCheckInput, now: datetime) -> tuple[datetime, datetime]:
    """The `created_at` range one check reads.

    It starts where the previous check's window ended, which is one interval before this check's due
    time. A check that runs late reads everything since then, so a missed tick loses no change.
    """
    due = check.next_check_at or now
    end = now - SETTLE
    start = due - timedelta(minutes=check.check_interval_minutes) - SETTLE
    return max(start, end - MAX_WINDOW), end


def _evaluate(team: Team, check: PlatformAlertCheckInput, *, now: datetime) -> Decision:
    start, end = change_window(check, now)
    muted = _in_quiet_hours(check, now, team.timezone)
    try:
        config = ErrorTrackingPlatformAlertConfig.model_validate(check.source_config)
    except ValidationError:
        # Saved through the same model, so this is a config an older version accepted.
        return _failed(check, _INVALID_CONFIG, transient=False, end=end, now=now, muted=muted)
    try:
        observations, cut = _observe_changes(team, config, start, end)
    except Exception as error:
        classified = classify_check_error(error)
        logger.exception("Error tracking alert check failed", check_id=str(check.id))
        return _failed(check, classified.user_message, transient=classified.is_transient, end=end, now=now, muted=muted)

    decision = decide_groups(
        check,
        observations,
        snapshot_of=lambda instance, _prior: _snapshot(check, instance),
        policy=POLICY,
        now=now,
        muted=muted,
    )
    recorded = decision.as_outcome(
        configuration_id=check.id,
        evaluation_key=_evaluation_key(check, end, now),
        grouping=check.grouping,
        query_duration_ms=None,
        results_cut=cut,
    )
    sends_messages = any(verdict.outcome.notification != NotificationAction.NONE for verdict in decision.verdicts)
    return recorded, _request(check, recorded, sends_messages=sends_messages)


def _observe_changes(
    team: Team, config: ErrorTrackingPlatformAlertConfig, start: datetime, end: datetime
) -> tuple[list[GroupObservation], bool]:
    """One firing observation per issue with a matching change, newest change first, and whether rows were cut."""
    triggers = set(config.condition.triggers)
    rows = list(
        ErrorTrackingIssueChange.objects.for_team(team.id)
        .filter(
            created_at__gte=start,
            created_at__lt=end,
            kind__in={_TRIGGER_KINDS[trigger] for trigger in triggers},
            # A bulk action over many issues would announce each one, so only single changes announce.
            bulk=False,
        )
        .order_by("-created_at")[: MAX_CHANGES_PER_CHECK + 1]
    )
    cut = len(rows) > MAX_CHANGES_PER_CHECK
    filters = _compiled_filters(team, config)
    observed: dict[str, GroupObservation] = {}
    for row in rows[:MAX_CHANGES_PER_CHECK]:
        trigger = _trigger_of(row)
        key = bounded_grouping_key(str(row.issue_id))
        if trigger is None or trigger not in triggers or key in observed:
            continue
        inputs = _filter_inputs(team.id, row, trigger)
        if filters is not None and not _passes(team, filters, inputs, row):
            continue
        observed[key] = GroupObservation(
            grouping_key=key,
            current_breached=True,
            labels={
                ISSUE_ID_LABEL: str(row.issue_id),
                ISSUE_NAME_LABEL: inputs.issue_name or "",
                TRIGGER_LABEL: trigger.value,
            },
        )
    return list(observed.values()), cut


def _trigger_of(row: ErrorTrackingIssueChange) -> ErrorTrackingPlatformAlertTrigger | None:
    snapshot = row.snapshot or {}
    if row.kind == ErrorTrackingIssueChange.Kind.CREATED:
        return ErrorTrackingPlatformAlertTrigger.ISSUE_CREATED
    if row.kind == ErrorTrackingIssueChange.Kind.STATUS_CHANGED and snapshot.get("status") == "active":
        if (row.data or {}).get("previous") != "active":
            return ErrorTrackingPlatformAlertTrigger.ISSUE_REOPENED
    if row.kind == ErrorTrackingIssueChange.Kind.ASSIGNEE_CHANGED and snapshot.get("assignee"):
        return ErrorTrackingPlatformAlertTrigger.ISSUE_ASSIGNED
    return None


def _compiled_filters(team: Team, config: ErrorTrackingPlatformAlertConfig) -> dict[str, Any] | None:
    filters = {"properties": config.filters.properties}
    if not filters_are_configured(filters):
        return None
    # Compiled at each check rather than stored, so a stored config never carries stale bytecode.
    return compile_alert_filters(team.id, filters)


def _filter_inputs(
    team_id: int, row: ErrorTrackingIssueChange, trigger: ErrorTrackingPlatformAlertTrigger
) -> AlertDeliveryWorkflowInputs:
    """The change as the native alerts' filter evaluator reads a transition, from the row's snapshot."""
    snapshot = row.snapshot or {}
    assignee = snapshot.get("assignee")
    return AlertDeliveryWorkflowInputs.build(
        notification_id=str(row.id),
        team_id=team_id,
        issue_id=str(row.issue_id),
        event=_TRIGGER_EVENTS[trigger],
        issue_name=snapshot.get("name"),
        status=snapshot.get("status"),
        severity=snapshot.get("severity"),
        assignee=assignee_property(assignee) if assignee else None,
        first_seen=snapshot.get("first_seen"),
        event_uuid=str(row.event_uuid) if row.event_uuid else None,
        event_timestamp=row.event_timestamp.isoformat() if row.event_timestamp else None,
    )


def _passes(
    team: Team, filters: dict[str, Any], inputs: AlertDeliveryWorkflowInputs, row: ErrorTrackingIssueChange
) -> bool:
    # A manual change has no exception, so a filter that needs one fails closed in the evaluator.
    exception_properties = None
    if inputs.event_uuid and inputs.event_timestamp:
        exception_properties = fetch_event_properties(
            team,
            _ExceptionRef(
                team_id=team.id,
                event_uuid=inputs.event_uuid,
                event_timestamp=inputs.event_timestamp,
                issue=_IssueRef(created_at=inputs.first_seen or inputs.event_timestamp),
            ),
        )
    outcome = evaluate_lifecycle_filters(
        filters, inputs, exception_properties, log_context={"change_id": str(row.id), "source": "platform_alert"}
    )
    return outcome == LifecycleFilterOutcome.MATCH


def _in_quiet_hours(check: PlatformAlertCheckInput, now: datetime, tz_name: str) -> bool:
    try:
        return is_utc_datetime_blocked(now, tz_name, parse_blocked_windows_tuples(check.schedule_restriction))
    except Exception:
        # A restriction that cannot be read must not hold back an announcement.
        logger.exception("Unparseable schedule restriction on an error tracking alert", check_id=str(check.id))
        return False


def _evaluation_key(check: PlatformAlertCheckInput, end: datetime, now: datetime) -> str:
    return f"slot:{slot_of(check.next_check_at, now)}|window:{end.isoformat()}"


def _snapshot(check: PlatformAlertCheckInput, instance: InstanceCheckState | None = None) -> AlertSnapshot:
    instance = instance or check.instance()
    return AlertSnapshot(
        state=AlertState(instance.state),
        cooldown=timedelta(minutes=check.cooldown_minutes),
        last_notified_at=instance.last_notified_at,
        snooze_until=instance.snooze_until,
        consecutive_failures=check.consecutive_failures,
        evaluation_periods=check.evaluation_periods,
        datapoints_to_alarm=check.datapoints_to_alarm,
        recent_events_breached=(),
        firing_started_at=instance.firing_started_at,
    )


def _failed(
    check: PlatformAlertCheckInput, message: str, *, transient: bool, end: datetime, now: datetime, muted: bool
) -> Decision:
    """A check that reached no verdict. The machine counts it toward BROKEN unless it is transient."""
    snapshot = _snapshot(check)
    outcome = evaluate_alert_check(
        snapshot,
        CheckInput(threshold_breached=False, error_message=message, is_transient_error=transient, muted=muted),
        now,
        policy=POLICY,
    )
    recorded = PlatformAlertOutcome.ungrouped(
        configuration_id=check.id,
        evaluation_key=_evaluation_key(check, end, now),
        consecutive_failures=outcome.consecutive_failures,
        kind=NOTIFICATION_EVENT_KINDS[outcome.notification],
        new_state=outcome.new_state.value,
        notified=outcome.update_last_notified_at,
        failed=True,
        firing_episode=decide_firing_episode(snapshot, outcome, now, policy=POLICY),
        muted_notification=muted_value(outcome),
        error_message=outcome.error_message,
        disable=outcome.disable,
    )
    return recorded, _request(check, recorded, sends_messages=outcome.notification != NotificationAction.NONE)


def _request(
    check: PlatformAlertCheckInput, recorded: PlatformAlertOutcome, *, sends_messages: bool
) -> AlertDeliveryRequest | None:
    # No incident actions: these alerts never resolve, so they cannot keep an incident manager in step.
    if not sends_messages:
        return None
    return AlertDeliveryRequest(
        source=SOURCE,
        team_id=check.team_id,
        configuration_id=str(check.id),
        evaluation_key=recorded.evaluation_key,
        destination_alert_id=str(check.destination_alert_id),
        event_ids_by_kind=EVENT_IDS_BY_KIND,
        event_ids_by_incident_action={},
        incident_actions={},
        sends_messages=True,
        source_alert_url=alert_url(check.team_id, check.id),
        owned_by_platform=check.owned_by_platform,
        overflowed=recorded.overflowed,
        overflow_is_lower_bound=recorded.overflow_is_lower_bound,
        parts=delivery_parts(recorded, {}),
    )


def _collect(decided: Sequence[Decision], *, team_id: int, slot: str) -> SourceBatchEvaluation:
    """The batch, held to one payload. A check past the payload keeps its due time for a later tick."""
    outcomes: list[PlatformAlertOutcome] = []
    deliveries: list[AlertDeliveryRequest] = []
    spent = 0
    deferred = 0
    for outcome, delivery in decided:
        size = payload_bytes(outcome) + (payload_bytes(delivery) if delivery is not None else 0)
        if spent + size > MAX_BATCH_PAYLOAD_BYTES:
            deferred += 1
            continue
        spent += size
        outcomes.append(outcome)
        if delivery is not None:
            deliveries.append(delivery)
    if deferred:
        logger.warning("Deferred error tracking alert checks", team_id=team_id, slot=slot, over_payload=deferred)
    return SourceBatchEvaluation(outcomes=tuple(outcomes), deliveries=tuple(deliveries), omitted=deferred)
