"""CDP internal events for user-driven issue lifecycle transitions.

Ingestion-driven transitions (created, reopened, spiking) are emitted by cymbal's
notifications worker (rust/cymbal/src/modes/notifications). These helpers cover the
transitions that happen in Django so destinations subscribed to issue lifecycle
events see the full picture.
"""

import json
from typing import Any, Optional

from django.db import transaction

import structlog

from posthog.cdp.internal_events import InternalEventEvent, InternalEventPerson, produce_internal_event
from posthog.models.user import User

from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
)

logger = structlog.get_logger(__name__)

ISSUE_RESOLVED_EVENT = "$error_tracking_issue_resolved"
ISSUE_SUPPRESSED_EVENT = "$error_tracking_issue_suppressed"
ISSUE_ASSIGNED_EVENT = "$error_tracking_issue_assigned"
ISSUE_UNASSIGNED_EVENT = "$error_tracking_issue_unassigned"
ISSUE_MERGED_EVENT = "$error_tracking_issue_merged"
ISSUE_SPLIT_EVENT = "$error_tracking_issue_split"
# Cymbal emits this same event when an ingested exception reopens an issue; manual
# reopens reuse it so reopened alerts cover both paths.
ISSUE_REOPENED_EVENT = "$error_tracking_issue_reopened"

STATUS_CHANGE_EVENTS: dict[str, str] = {
    ErrorTrackingIssue.Status.ACTIVE: ISSUE_REOPENED_EVENT,
    ErrorTrackingIssue.Status.RESOLVED: ISSUE_RESOLVED_EVENT,
    ErrorTrackingIssue.Status.SUPPRESSED: ISSUE_SUPPRESSED_EVENT,
}


def status_label(status: str) -> str:
    # Cymbal emits display-cased status values ("Active", "Resolved") on the
    # ingestion-driven events; keep the same shape here so filters match both.
    try:
        return str(ErrorTrackingIssue.Status(status).label)
    except ValueError:
        return status


def assignee_property(assignee: dict[str, Any]) -> str:
    # Wire-compatible with cymbal's `Assignee` serialization on created/reopened events
    # (compact serde JSON, adjacently tagged, numeric user ids and string role ids), so
    # exact-match filters on the assignee property behave the same across all events.
    assignee_id = int(assignee["id"]) if assignee["type"] == "user" else str(assignee["id"])
    return json.dumps({"type": assignee["type"], "id": assignee_id}, separators=(",", ":"))


def _current_assignee_property(issue: ErrorTrackingIssue) -> Optional[str]:
    assignment = ErrorTrackingIssueAssignment.objects.filter(issue_id=issue.id).only("user_id", "role_id").first()
    if assignment is None:
        return None
    if assignment.user_id:
        return assignee_property({"type": "user", "id": assignment.user_id})
    if assignment.role_id:
        return assignee_property({"type": "role", "id": assignment.role_id})
    return None


def _issue_fingerprint_for_links(issue: ErrorTrackingIssue) -> Optional[str]:
    # Existing Error Tracking destination templates expect `fingerprint`. Manual
    # transitions have no triggering exception, so include one currently attached
    # fingerprint for compatibility. Fingerprint routes follow current ownership
    # after merges/splits; `distinct_id` identifies the issue that emitted the
    # event. The ordering only keeps the pick deterministic.
    return (
        ErrorTrackingIssueFingerprintV2.objects.filter(team_id=issue.team_id, issue_id=issue.id)
        .order_by("first_seen", "id")
        .values_list("fingerprint", flat=True)
        .first()
    )


def produce_issue_lifecycle_event_on_commit(
    *,
    event: str,
    issue: ErrorTrackingIssue,
    user: Optional[User],
    status: Optional[str] = None,
    extra_properties: Optional[dict[str, Any]] = None,
) -> None:
    # Snapshot everything now: the issue row may be mutated again (or deleted, for
    # merge sources) before the surrounding transaction commits.
    team_id = issue.team_id
    # `exception_timestamp` stays absent on manual transitions so the issue scene
    # falls back to the issue's latest exception instead of an empty window around
    # the mutation.
    fingerprint = _issue_fingerprint_for_links(issue)
    current_assignee = _current_assignee_property(issue)
    # Same issue-property set the ingestion-driven producer emits (see
    # produce_issue_lifecycle_internal_event), so destination property filters
    # match both paths.
    properties: dict[str, Any] = {
        "name": issue.name,
        "description": issue.description,
        "issue_description": issue.description,
        "first_seen": issue.created_at.isoformat(),
        "severity": issue.severity,
        "status": status_label(status if status is not None else issue.status),
        **({"fingerprint": fingerprint} if fingerprint is not None else {}),
        **({"assignee": current_assignee} if current_assignee is not None else {}),
        **(extra_properties or {}),
    }
    internal_event = InternalEventEvent(event=event, distinct_id=str(issue.id), properties=properties)

    person = None
    if user is not None:
        # Deliberately a minimal actor subset: person reaches customer-configured
        # destinations verbatim (the default webhook body sends `{person}`), so no
        # full user serializer here.
        person = InternalEventPerson(
            id=str(user.id),
            properties={
                "id": str(user.id),
                "distinct_id": user.distinct_id,
                "email": user.email,
                "first_name": user.first_name,
            },
        )

    def _produce() -> None:
        try:
            produce_internal_event(team_id=team_id, event=internal_event, person=person)
        except Exception:
            # Already logged by produce_internal_event; alert emission must never
            # fail the mutation that triggered it.
            pass

    transaction.on_commit(_produce)
