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

from posthog.api.shared import UserBasicSerializer
from posthog.cdp.internal_events import InternalEventEvent, InternalEventPerson, produce_internal_event
from posthog.models.user import User

from products.error_tracking.backend.models import ErrorTrackingIssue

logger = structlog.get_logger(__name__)

ISSUE_RESOLVED_EVENT = "$error_tracking_issue_resolved"
ISSUE_SUPPRESSED_EVENT = "$error_tracking_issue_suppressed"
ISSUE_ASSIGNED_EVENT = "$error_tracking_issue_assigned"
ISSUE_MERGED_EVENT = "$error_tracking_issue_merged"
# Cymbal emits this same event when an ingested exception reopens an issue; manual
# reopens reuse it (without exception props) so reopened alerts cover both paths.
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
    properties: dict[str, Any] = {
        "name": issue.name,
        "description": issue.description,
        "status": status_label(status if status is not None else issue.status),
        **(extra_properties or {}),
    }
    internal_event = InternalEventEvent(event=event, distinct_id=str(issue.id), properties=properties)

    person = None
    if user is not None:
        user_data = UserBasicSerializer(user).data
        person = InternalEventPerson(id=str(user_data["id"]), properties=dict(user_data))

    def _produce() -> None:
        try:
            produce_internal_event(team_id=team_id, event=internal_event, person=person)
        except Exception:
            # Already logged by produce_internal_event; alert emission must never
            # fail the mutation that triggered it.
            pass

    transaction.on_commit(_produce)
