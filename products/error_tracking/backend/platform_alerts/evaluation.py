"""Evaluation of due error tracking alerts on the shared alerts platform.

Each check reads the issue changes recorded since the previous check, keeps the ones its triggers
and filters match, and reports one firing group per issue. An issue with no new change in a later
check resolves without a message, so the next matching change on it is announced again. Each
announcement starts a firing episode, and the platform threads messages by episode, so a later
change on the same issue posts a new message rather than a reply.

This reads and decides. It writes nothing, so a retried attempt reads the same changes and makes
the same decisions. The platform records the outcomes in its own activity.
"""

import time
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Final

from django.db.models import Q

import structlog
from pydantic import ValidationError

from posthog.dataclasses import frozen
from posthog.models import Team

from products.alerts_platform.backend.facade.api import due_checks, slot_of
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
from products.alerts_platform.backend.facade.scheduling import (
    BlockedWindow,
    is_utc_datetime_blocked,
    parse_blocked_windows_tuples,
)
from products.error_tracking.backend.facade.contracts import LifecycleFilterOutcome
from products.error_tracking.backend.logic.alerts import AlertValidationError, compile_alert_filters
from products.error_tracking.backend.logic.assignees import assignee_property
from products.error_tracking.backend.logic.lifecycle_events import status_label
from products.error_tracking.backend.models import ErrorTrackingIssueChange, ErrorTrackingIssueFingerprintV2
from products.error_tracking.backend.platform_alerts.source_config import (
    ErrorTrackingPlatformAlertConfig,
    ErrorTrackingPlatformAlertTrigger,
)
from products.error_tracking.backend.platform_alerts.wording import (
    FINGERPRINT_DETAIL,
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
from products.error_tracking.backend.temporal.lifecycle.event_properties import (
    IssueCreatedEventNotFoundError,
    fetch_event_properties,
)

logger = structlog.get_logger(__name__)

SOURCE: Final = SourceKind.ERROR_TRACKING
# A change is announced when it happens, and an issue with no new change resolves without a message.
# A firing issue is announced again for each new change, which cooldown can still hold back.
POLICY: Final = replace(PLATFORM_DEFAULT_ALERT_POLICY, notify_resolve=False, renotify_while_firing=True)

# A change row commits after its `created_at`, so a window that ended now would miss a row still in
# its transaction and never read it again.
SETTLE: Final = timedelta(seconds=60)
# How far back a check that ran late reads. Older changes are no longer news.
MAX_WINDOW: Final = timedelta(hours=24)
# Changes one check reads, newest first. A check that finds more reports what it read and logs the cut.
MAX_CHANGES_PER_CHECK: Final = 1_000
# The batch's read time, which `EVALUATE_START_TO_CLOSE` in the workflow sits above. A check the
# budget has no room for records nothing, so it keeps its due time and a later tick reads its window.
BATCH_BUDGET_SECONDS: Final = 25

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

# Each trigger's rows, so the read returns only changes the alert can announce.
_TRIGGER_ROWS: Final[dict[ErrorTrackingPlatformAlertTrigger, Q]] = {
    # Only ingestion creates a new error. A split's new issues are a person regrouping known errors.
    ErrorTrackingPlatformAlertTrigger.ISSUE_CREATED: Q(
        kind=ErrorTrackingIssueChange.Kind.CREATED, actor_type=ErrorTrackingIssueChange.ActorType.INGESTION
    ),
    ErrorTrackingPlatformAlertTrigger.ISSUE_REOPENED: Q(
        kind=ErrorTrackingIssueChange.Kind.STATUS_CHANGED, snapshot__status="active"
    )
    & ~Q(data__previous="active"),
    ErrorTrackingPlatformAlertTrigger.ISSUE_ASSIGNED: Q(kind=ErrorTrackingIssueChange.Kind.ASSIGNEE_CHANGED)
    & ~Q(snapshot__assignee=None),
}

_INVALID_CONFIG: Final = "The alert's configuration is no longer valid. Edit the alert to fix it."
_CHECK_FAILED: Final = "The alert could not read the issue changes. It will try again at its next check."

Decision = tuple[PlatformAlertOutcome, AlertDeliveryRequest | None]


class _OutOfTime(Exception):
    pass


@frozen
class ChangeWindow:
    """The `created_at` range one check reads, start included and end excluded."""

    start: datetime
    end: datetime


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
    deadline = time.monotonic() + BATCH_BUDGET_SECONDS
    decided: list[Decision] = []
    # Start each tick at a different check, so one that never fits the budget cannot hold back the rest.
    first = int(cutoff.timestamp() // 60) % len(checks)
    for check in (*checks[first:], *checks[:first]):
        if time.monotonic() >= deadline:
            break
        decision = _evaluate(team, check, now=cutoff, deadline=deadline)
        if decision is not None:
            decided.append(decision)
    return _collect(decided, team_id=team_id, slot=slot, unrecorded=len(checks) - len(decided))


def change_window(
    check: PlatformAlertCheckInput, now: datetime, *, tz_name: str, quiet_hours: list[BlockedWindow] | None
) -> ChangeWindow:
    """The range one check reads.

    It starts where the previous reading check's window ended, a settle margin before that check's due
    time. A check that runs late reads everything since then, so a missed tick loses no change. Two
    kinds of earlier check read nothing, so the window reaches back over them: a failed one, counted
    by the configuration's failures, and one in quiet hours, which the platform does not schedule.
    """
    # On the minute, as every scheduled due time is: an edit moves it to an arbitrary second.
    due = (check.next_check_at or now).replace(second=0, microsecond=0)
    end = now - SETTLE
    oldest = end - MAX_WINDOW
    interval = timedelta(minutes=check.check_interval_minutes)
    previous = due
    for _ in range(1 + check.consecutive_failures):
        previous -= interval
        while previous > oldest and quiet_hours and is_utc_datetime_blocked(previous, tz_name, quiet_hours):
            previous -= interval
    return ChangeWindow(start=max(previous - SETTLE, oldest), end=end)


def _evaluate(team: Team, check: PlatformAlertCheckInput, *, now: datetime, deadline: float) -> Decision | None:
    """The check's decision, or None when it must keep its due time so a later tick reads its window again."""
    quiet_hours = _quiet_hours(check)
    window = change_window(check, now, tz_name=team.timezone, quiet_hours=quiet_hours)
    # The platform schedules no check in quiet hours, so one here came from an edit. It reads nothing,
    # and the first check after them reads its changes.
    muted = bool(quiet_hours) and is_utc_datetime_blocked(now, team.timezone, quiet_hours)
    try:
        config = ErrorTrackingPlatformAlertConfig.model_validate(check.source_config)
        filters = _compiled_filters(team, config)
    except (ValidationError, AlertValidationError):
        # Saved through the same checks, so this is a config an older version accepted.
        return _failed(check, _INVALID_CONFIG, transient=False, end=window.end, now=now, muted=muted)
    try:
        observations, cut = ([], False) if muted else _observe_changes(team, config, filters, window, deadline=deadline)
        fingerprints = _fingerprints(team.id, observations)
    except _OutOfTime:
        return None
    except Exception:
        # Recorded so the alert shows the failure and can break. `change_window` reads this window
        # again at the next check, because the failure count widens it.
        logger.exception("Error tracking alert check failed", check_id=str(check.id))
        return _failed(check, _CHECK_FAILED, transient=False, end=window.end, now=now, muted=muted)
    if cut:
        logger.warning("Error tracking alert check read its row limit", check_id=str(check.id))

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
        evaluation_key=_evaluation_key(check, window.end, now),
        grouping=check.grouping,
        query_duration_ms=None,
        results_cut=cut,
    )
    recorded = _with_fingerprints(recorded, fingerprints)
    sends_messages = any(verdict.outcome.notification != NotificationAction.NONE for verdict in decision.verdicts)
    return recorded, _request(check, recorded, sends_messages=sends_messages)


def _observe_changes(
    team: Team,
    config: ErrorTrackingPlatformAlertConfig,
    filters: dict[str, Any] | None,
    window: ChangeWindow,
    *,
    deadline: float,
) -> tuple[list[GroupObservation], bool]:
    """One firing observation per issue with a matching change, and whether the read hit its limit."""
    triggers = set(config.condition.triggers)
    matches_trigger = Q()
    for wanted in triggers:
        matches_trigger |= _TRIGGER_ROWS[wanted]
    rows = list(
        ErrorTrackingIssueChange.objects.for_team(team.id)
        .filter(
            matches_trigger,
            created_at__gte=window.start,
            created_at__lt=window.end,
            # A bulk action over many issues would announce each one, so only single changes announce.
            bulk=False,
        )
        .order_by("-created_at")[: MAX_CHANGES_PER_CHECK + 1]
    )
    cut = len(rows) > MAX_CHANGES_PER_CHECK
    observed: dict[str, GroupObservation] = {}
    for row in rows[:MAX_CHANGES_PER_CHECK]:
        key = bounded_grouping_key(str(row.issue_id))
        trigger = _trigger_of(row)
        # Filters run before an issue is counted once, so an older change that matches still fires it.
        if key in observed or trigger is None or trigger not in triggers:
            continue
        inputs = _filter_inputs(team.id, row, trigger)
        if filters is not None:
            if time.monotonic() >= deadline:
                raise _OutOfTime
            if not _passes(team, filters, inputs, row):
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
    if (
        row.kind == ErrorTrackingIssueChange.Kind.CREATED
        and row.actor_type == ErrorTrackingIssueChange.ActorType.INGESTION
    ):
        return ErrorTrackingPlatformAlertTrigger.ISSUE_CREATED
    if row.kind == ErrorTrackingIssueChange.Kind.STATUS_CHANGED and snapshot.get("status") == "active":
        if (row.data or {}).get("previous") != "active":
            return ErrorTrackingPlatformAlertTrigger.ISSUE_REOPENED
    if row.kind == ErrorTrackingIssueChange.Kind.ASSIGNEE_CHANGED and snapshot.get("assignee"):
        return ErrorTrackingPlatformAlertTrigger.ISSUE_ASSIGNED
    return None


def _fingerprints(team_id: int, observations: Sequence[GroupObservation]) -> dict[str, str]:
    """One fingerprint per observed issue, which a message links by so the link survives a merge."""
    issue_ids = [observation.labels[ISSUE_ID_LABEL] for observation in observations]
    if not issue_ids:
        return {}
    rows = (
        ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, issue_id__in=issue_ids)
        # The earliest fingerprint, as the native alerts pick it, so the pick is deterministic.
        .order_by("issue_id", "first_seen", "id")
        .distinct("issue_id")
        .values_list("issue_id", "fingerprint")
    )
    return {str(issue_id): fingerprint for issue_id, fingerprint in rows}


def _with_fingerprints(recorded: PlatformAlertOutcome, fingerprints: dict[str, str]) -> PlatformAlertOutcome:
    if not fingerprints:
        return recorded
    groups = tuple(
        replace(group, source_detail={**group.source_detail, FINGERPRINT_DETAIL: fingerprint})
        if (fingerprint := fingerprints.get(group.labels.get(ISSUE_ID_LABEL, "")))
        else group
        for group in recorded.groups
    )
    return replace(recorded, groups=groups)


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
        # Display-cased, as the native producers send it, so a filter on status matches both.
        status=status_label(snapshot["status"]) if snapshot.get("status") else None,
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
        exception_properties = _exception_properties(
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


def _exception_properties(team: Team, ref: "_ExceptionRef") -> dict[str, object] | None:
    """The exception's properties, or None when retrying cannot find them.

    A missing or malformed event fails closed for this change alone, so a filter on the issue still
    decides it and the rest of the check goes on. Any other error propagates, and the check is read again.
    """
    try:
        return fetch_event_properties(team, ref)
    except (IssueCreatedEventNotFoundError, ValueError, TypeError):
        logger.warning("Error tracking alert change has no readable exception", event_uuid=ref.event_uuid)
        return None


def _quiet_hours(check: PlatformAlertCheckInput) -> list[BlockedWindow] | None:
    try:
        return parse_blocked_windows_tuples(check.schedule_restriction)
    except Exception:
        # A restriction that cannot be read must not hold back an announcement.
        logger.exception("Unparseable schedule restriction on an error tracking alert", check_id=str(check.id))
        return None


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


def _collect(decided: Sequence[Decision], *, team_id: int, slot: str, unrecorded: int) -> SourceBatchEvaluation:
    """The batch, held to one payload. A check past the payload or the budget keeps its due time for a later tick."""
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
    if deferred or unrecorded:
        logger.warning(
            "Deferred error tracking alert checks",
            team_id=team_id,
            slot=slot,
            over_payload=deferred,
            unrecorded=unrecorded,
        )
    return SourceBatchEvaluation(outcomes=tuple(outcomes), deliveries=tuple(deliveries), omitted=deferred + unrecorded)
