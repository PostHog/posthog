"""The CDP internal events subscription: lifecycle events built from issue change rows.

These replace the events Django mutations used to emit after commit, so they reuse the
same property builder and event names. State fields come from the row's snapshot;
description, fingerprint and assignee display values are loaded at dispatch, as the old
producer read them at commit.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

import structlog

from posthog.cdp.internal_events import (
    InternalEventEvent,
    InternalEventPerson,
    flush_internal_events_producer,
    produce_internal_event,
)
from posthog.dataclasses import frozen
from posthog.kafka_client.client import ProduceResult

from products.error_tracking.backend.logic.assignees import ResolvedAssignee, assignee_property
from products.error_tracking.backend.logic.change_subscriptions import ChangeContext, Delivery, Kind, Need, Subscription
from products.error_tracking.backend.logic.issue_changes import (
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
from products.error_tracking.backend.models import ErrorTrackingIssueChange

logger = structlog.get_logger(__name__)

KAFKA_DELIVERY_TIMEOUT_SECONDS = 30


@frozen
class ChangeEvent:
    change_id: UUID
    team_id: int
    event: InternalEventEvent
    person: InternalEventPerson | None


@frozen
class _EventSpec:
    name: str
    extra_properties: dict[str, Any] | None


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


def _assignee_at_change(change: ErrorTrackingIssueChange, context: ChangeContext) -> ResolvedAssignee | None:
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


def build_change_event(delivery: Delivery) -> ChangeEvent:
    change, context = delivery.change, delivery.context
    spec = _event_spec(change)
    snapshot = change.snapshot
    properties = issue_event_properties(
        name=snapshot["name"],
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
    def deliver(self, deliveries: Sequence[Delivery]) -> set[UUID]:
        events: list[ChangeEvent] = []
        for delivery in deliveries:
            try:
                events.append(build_change_event(delivery))
            except Exception:
                # A malformed row cannot become an event on any retry, so it is dropped, not retried.
                logger.exception(
                    "error_tracking_change_event_build_failed",
                    team_id=delivery.change.team_id,
                    change_id=str(delivery.change.id),
                )
        undelivered: set[UUID] = set()
        pending: list[tuple[ChangeEvent, ProduceResult]] = []
        for event in events:
            try:
                pending.append(
                    (event, produce_internal_event(team_id=event.team_id, event=event.event, person=event.person))
                )
            except Exception:
                # Already logged by produce_internal_event.
                undelivered.add(event.change_id)
        if pending:
            flush_internal_events_producer(KAFKA_DELIVERY_TIMEOUT_SECONDS)
        for event, result in pending:
            try:
                result.get(timeout=0)
            except Exception:
                logger.exception(
                    "error_tracking_change_event_not_delivered", team_id=event.team_id, change_id=str(event.change_id)
                )
                undelivered.add(event.change_id)
        return undelivered


CDP_INTERNAL_EVENTS = Subscription(
    key="cdp-internal-events",
    kinds=frozenset({Kind.STATUS_CHANGED, Kind.ASSIGNEE_CHANGED, Kind.MERGED, Kind.SPLIT}),
    needs=frozenset(
        {Need.DESCRIPTION, Need.FINGERPRINT, Need.CURRENT_ASSIGNEE, Need.SNAPSHOT_ASSIGNEE_USER, Need.ACTOR}
    ),
    matches=_has_event,
    sink=InternalEventsSink(),
)
