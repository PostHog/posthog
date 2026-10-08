"""Lifecycle internal events built from issue change rows.

The change dispatcher emits these in place of the events Django mutations used to
emit after commit, so they reuse the same property builder and event names. State
fields come from the row's snapshot; description, fingerprint and assignee display
values are read when the event is built, as the old producer read them at commit.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from posthog.cdp.internal_events import InternalEventEvent, InternalEventPerson
from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.user import User

from products.error_tracking.backend.logic.assignees import (
    ResolvedAssignee,
    assignee_property,
    resolve_current_assignees,
    resolve_user_assignees,
)
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
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueChange,
    ErrorTrackingIssueFingerprintV2,
)


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


def _event_spec(change: ErrorTrackingIssueChange) -> _EventSpec | None:
    """The event a change emits, or None for kinds that had no internal event before."""
    snapshot_assignee = AssigneeRef.from_json(change.snapshot.get("assignee"))
    match parse_change_data(change.kind, change.data):
        case StatusChanged(previous=previous):
            event = STATUS_CHANGE_EVENTS.get(change.snapshot["status"])
            if event is None:
                return None
            return _EventSpec(name=event, extra_properties={"previous_status": status_label(previous)})
        case AssigneeChanged(previous=previous):
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
    return None


def _assignee_at_change(
    snapshot_assignee: AssigneeRef | None,
    current: ResolvedAssignee | None,
    users: dict[int, ResolvedAssignee],
) -> ResolvedAssignee | None:
    # The snapshot says who the change left assigned, and the event names that assignee even
    # if the issue was reassigned before dispatch. A role reassigned meanwhile loses its display
    # name: role names belong to access control, which error tracking cannot read.
    if snapshot_assignee is None:
        return None
    property_value = assignee_property(snapshot_assignee.to_json())
    if current is not None and current.property_value == property_value:
        return current
    if snapshot_assignee.type == "user" and int(snapshot_assignee.id) in users:
        return users[int(snapshot_assignee.id)]
    return ResolvedAssignee(property_value=property_value, name=None, email=None)


def _first_fingerprints(team_id: int, issue_ids: set[UUID]) -> dict[UUID, str]:
    # Same pick as the old producer: the earliest fingerprint, with the id as tiebreaker.
    return dict(
        ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, issue_id__in=issue_ids)
        .order_by("issue_id", "first_seen", "id")
        .distinct("issue_id")
        .values_list("issue_id", "fingerprint")
    )


def build_change_events(team_id: int, changes: Sequence[ErrorTrackingIssueChange]) -> list[ChangeEvent]:
    specs = [(change, spec) for change in changes if (spec := _event_spec(change)) is not None]
    if not specs:
        return []
    issue_ids = {change.issue_id for change, _ in specs}
    descriptions = dict(
        ErrorTrackingIssue.objects.filter(team_id=team_id, id__in=issue_ids).values_list("id", "description")
    )
    fingerprints = _first_fingerprints(team_id, issue_ids)
    assignees = resolve_current_assignees(list(issue_ids))
    actor_ids = {change.actor_user_id for change, _ in specs if change.actor_user_id is not None}
    users = {user.id: user for user in User.objects.filter(id__in=actor_ids)}
    snapshot_assignees = [AssigneeRef.from_json(change.snapshot.get("assignee")) for change, _ in specs]
    assigned_user_ids = {int(ref.id) for ref in snapshot_assignees if ref is not None and ref.type == "user"}
    assigned_users = (
        resolve_user_assignees(Team.objects.only("organization_id").get(id=team_id).organization_id, assigned_user_ids)
        if assigned_user_ids
        else {}
    )

    events: list[ChangeEvent] = []
    for change, spec in specs:
        snapshot = change.snapshot
        properties = issue_event_properties(
            name=snapshot["name"],
            description=descriptions.get(change.issue_id),
            first_seen=snapshot["first_seen"],
            severity=snapshot["severity"],
            status=snapshot["status"],
            fingerprint=fingerprints.get(change.issue_id),
            assignee=_assignee_at_change(
                AssigneeRef.from_json(snapshot.get("assignee")), assignees.get(change.issue_id), assigned_users
            ),
            extra_properties=spec.extra_properties,
        )
        user = users.get(change.actor_user_id) if change.actor_user_id is not None else None
        events.append(
            ChangeEvent(
                change_id=change.id,
                team_id=team_id,
                # The change id doubles as the event uuid, so a retried emission is recognizable downstream.
                event=InternalEventEvent(
                    event=spec.name,
                    distinct_id=str(change.issue_id),
                    properties=properties,
                    uuid=str(change.id),
                    timestamp=change.created_at.isoformat(),
                ),
                person=event_person(user) if user is not None else None,
            )
        )
    return events
