"""The CDP internal events subscription: lifecycle events built from issue change rows.

These replace the events Django mutations used to emit after commit, so they reuse the
same property builder and event names. State fields come from the row's snapshot;
description, fingerprint and assignee display values are loaded at dispatch, as the old
producer read them at commit.
"""

from collections.abc import Collection, Mapping, Sequence
from typing import Any
from uuid import UUID

import structlog
from confluent_kafka import KafkaError, KafkaException

from posthog.dataclasses import frozen
from posthog.kafka_client.client import ProduceResult
from posthog.models.team import Team
from posthog.models.user import User

from products.cdp.backend.internal_events import (
    InternalEventEvent,
    InternalEventPerson,
    flush_internal_events_producer,
    produce_internal_event,
)
from products.error_tracking.backend.logic.assignees import (
    ResolvedAssignee,
    assignee_property,
    resolve_current_assignees,
    resolve_user_assignees,
)
from products.error_tracking.backend.logic.change_subscriptions import Kind, Subscription
from products.error_tracking.backend.logic.issue_changes import (
    MAX_ISSUE_NAME_LENGTH,
    AssigneeChanged,
    AssigneeRef,
    Merged,
    Split,
    StatusChanged,
    parse_change_data,
)
from products.error_tracking.backend.logic.lifecycle_events import (
    ISSUE_ASSIGNED_EVENT,
    ISSUE_MERGED_EVENT,
    ISSUE_SPLIT_EVENT,
    ISSUE_UNASSIGNED_EVENT,
    STATUS_CHANGE_EVENTS,
    event_person,
    issue_event_properties,
    status_label,
)
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueChange,
    ErrorTrackingIssueFingerprintV2,
)

logger = structlog.get_logger(__name__)

KAFKA_DELIVERY_TIMEOUT_SECONDS = 30


@frozen
class ChangeEvent:
    change_id: UUID
    team_id: int
    event: InternalEventEvent
    person: InternalEventPerson | None


@frozen
class _EventContext:
    names: Mapping[UUID, str | None]
    descriptions: Mapping[UUID, str | None]
    fingerprints: Mapping[UUID, str]
    # The issue's assignee now, with display values.
    current_assignees: Mapping[UUID, ResolvedAssignee]
    # Display values for the users that change snapshots name as assignee.
    snapshot_assignee_users: Mapping[int, ResolvedAssignee]
    actors: Mapping[int, User]


@frozen
class _EventSpec:
    name: str
    extra_properties: dict[str, Any] | None


def _snapshot_assignee_user_id(change: ErrorTrackingIssueChange) -> int | None:
    # A malformed snapshot must not fail the load for the team's other changes.
    try:
        ref = AssigneeRef.from_json(change.snapshot.get("assignee"))
        return int(ref.id) if ref is not None and ref.type == "user" else None
    except (KeyError, TypeError, ValueError):
        logger.warning("error_tracking_change_malformed_snapshot_assignee", change_id=str(change.id))
        return None


def _load_event_context(team_id: int, changes: Collection[ErrorTrackingIssueChange]) -> _EventContext:
    issue_ids = {change.issue_id for change in changes}
    organization_id = Team.objects.only("organization_id").get(id=team_id).organization_id
    issue_texts = ErrorTrackingIssue.objects.filter(team_id=team_id, id__in=issue_ids).values_list(
        "id", "name", "description"
    )
    # Same pick as the lifecycle event producer: the earliest fingerprint, with the id as tiebreaker.
    fingerprints = dict(
        ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, issue_id__in=issue_ids)
        .order_by("issue_id", "first_seen", "id")
        .distinct("issue_id")
        .values_list("issue_id", "fingerprint")
    )
    user_ids = {user_id for change in changes if (user_id := _snapshot_assignee_user_id(change)) is not None}
    actor_ids = {change.actor_user_id for change in changes if change.actor_user_id is not None}
    return _EventContext(
        names={issue_id: name for issue_id, name, _ in issue_texts},
        descriptions={issue_id: description for issue_id, _, description in issue_texts},
        fingerprints=fingerprints,
        current_assignees=resolve_current_assignees(list(issue_ids)),
        snapshot_assignee_users=resolve_user_assignees(organization_id, user_ids) if user_ids else {},
        # A user who left the organization since the change must not have their profile sent to it.
        actors={
            user.id: user
            for user in User.objects.filter(id__in=actor_ids, organization_membership__organization_id=organization_id)
        }
        if actor_ids
        else {},
    )


def _has_event(change: ErrorTrackingIssueChange) -> bool:
    # Archived and pending release have no lifecycle event yet.
    return change.kind != Kind.STATUS_CHANGED or change.snapshot.get("status") in STATUS_CHANGE_EVENTS


def _event_spec(change: ErrorTrackingIssueChange) -> _EventSpec:
    match parse_change_data(change.kind, change.data):
        case StatusChanged(previous=previous):
            return _EventSpec(
                name=STATUS_CHANGE_EVENTS[change.snapshot["status"]],
                extra_properties={"previous_status": status_label(previous)},
            )
        case AssigneeChanged(previous=previous):
            snapshot_assignee = AssigneeRef.from_json(change.snapshot.get("assignee"))
            if snapshot_assignee is not None:
                return _EventSpec(
                    name=ISSUE_ASSIGNED_EVENT,
                    extra_properties={"assignee": assignee_property(snapshot_assignee.to_json())},
                )
            return _EventSpec(
                name=ISSUE_UNASSIGNED_EVENT,
                extra_properties={"previous_assignee": assignee_property(previous.to_json())} if previous else None,
            )
        case Merged(merged_issue_ids=merged_issue_ids):
            return _EventSpec(
                name=ISSUE_MERGED_EVENT,
                extra_properties={"merged_issue_ids": [str(issue_id) for issue_id in merged_issue_ids]},
            )
        case Split(new_issue_ids=new_issue_ids):
            return _EventSpec(
                name=ISSUE_SPLIT_EVENT,
                extra_properties={"split_issue_ids": [str(issue_id) for issue_id in new_issue_ids]},
            )
    raise ValueError(f"No internal event for issue change kind: {change.kind}")


def _assignee_at_change(change: ErrorTrackingIssueChange, context: _EventContext) -> ResolvedAssignee | None:
    # The snapshot says who the change left assigned, and the event names that assignee even
    # if the issue was reassigned before dispatch. A role reassigned meanwhile loses its display
    # name: role names belong to access control, which error tracking cannot read.
    snapshot_assignee = AssigneeRef.from_json(change.snapshot.get("assignee"))
    if snapshot_assignee is None:
        return None
    property_value = assignee_property(snapshot_assignee.to_json())
    current = context.current_assignees.get(change.issue_id)
    if current is not None and current.property_value == property_value:
        return current
    if snapshot_assignee.type == "user" and int(snapshot_assignee.id) in context.snapshot_assignee_users:
        return context.snapshot_assignee_users[int(snapshot_assignee.id)]
    return ResolvedAssignee(property_value=property_value, name=None, email=None)


def _name_at_change(change: ErrorTrackingIssueChange, context: _EventContext) -> str | None:
    # The snapshot caps the name. Use the whole current name when the capped one is its prefix.
    snapshot_name: str | None = change.snapshot["name"]
    current = context.names.get(change.issue_id)
    if snapshot_name and len(snapshot_name) == MAX_ISSUE_NAME_LENGTH and current and current.startswith(snapshot_name):
        return current
    return snapshot_name


def _is_permanent_rejection(error: Exception) -> bool:
    kafka_error = error.args[0] if isinstance(error, KafkaException) and error.args else None
    return isinstance(kafka_error, KafkaError) and kafka_error.name() in {"MSG_SIZE_TOO_LARGE", "_MSG_SIZE_TOO_LARGE"}


def build_change_event(change: ErrorTrackingIssueChange, context: _EventContext) -> ChangeEvent:
    spec = _event_spec(change)
    snapshot = change.snapshot
    properties = issue_event_properties(
        name=_name_at_change(change, context),
        description=context.descriptions.get(change.issue_id),
        first_seen=snapshot["first_seen"],
        severity=snapshot["severity"],
        status=snapshot["status"],
        fingerprint=context.fingerprints.get(change.issue_id),
        assignee=_assignee_at_change(change, context),
        extra_properties=spec.extra_properties,
    )
    user = context.actors.get(change.actor_user_id) if change.actor_user_id is not None else None
    return ChangeEvent(
        change_id=change.id,
        team_id=change.team_id,
        # The change id doubles as the event uuid, so a redelivered event is recognizable downstream.
        event=InternalEventEvent(
            event=spec.name,
            distinct_id=str(change.issue_id),
            properties=properties,
            uuid=str(change.id),
            timestamp=change.created_at.isoformat(),
        ),
        person=event_person(user) if user is not None else None,
    )


class InternalEventsSink:
    def deliver(self, team_id: int, changes: Sequence[ErrorTrackingIssueChange]) -> set[UUID]:
        context = _load_event_context(team_id, changes)
        events: list[ChangeEvent] = []
        for change in changes:
            try:
                events.append(build_change_event(change, context))
            except Exception:
                # A malformed row cannot become an event on any retry, so it is dropped, not retried.
                logger.exception("error_tracking_change_event_build_failed", team_id=team_id, change_id=str(change.id))
        undelivered: set[UUID] = set()
        pending: list[tuple[ChangeEvent, ProduceResult]] = []
        for event in events:
            try:
                pending.append(
                    (event, produce_internal_event(team_id=event.team_id, event=event.event, person=event.person))
                )
            except Exception as error:
                # Already logged by produce_internal_event.
                if not _is_permanent_rejection(error):
                    undelivered.add(event.change_id)
        if pending:
            try:
                flush_internal_events_producer(KAFKA_DELIVERY_TIMEOUT_SECONDS)
            except Exception:
                logger.exception("error_tracking_change_event_flush_failed")
                return undelivered | {event.change_id for event, _ in pending}
        for event, result in pending:
            try:
                result.get(timeout=0)
            except Exception as error:
                logger.exception(
                    "error_tracking_change_event_not_delivered", team_id=event.team_id, change_id=str(event.change_id)
                )
                # Kafka rejects the same oversized event on every retry, so retrying it would block the outbox.
                if not _is_permanent_rejection(error):
                    undelivered.add(event.change_id)
        return undelivered


CDP_INTERNAL_EVENTS = Subscription(
    key="cdp-internal-events",
    kinds=frozenset({Kind.STATUS_CHANGED, Kind.ASSIGNEE_CHANGED, Kind.MERGED, Kind.SPLIT}),
    matches=_has_event,
    sink=InternalEventsSink(),
)
