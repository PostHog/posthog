"""Assignee wire format shared by the lifecycle event producers.

Kept apart from lifecycle_events so the Temporal activities can read an issue's
current assignee without importing the alert types, which would close an import cycle.
"""

import json
from typing import Any, Optional

from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueAssignment


def assignee_property(assignee: dict[str, Any]) -> str:
    # Wire-compatible with cymbal's `Assignee` serialization on created/reopened events
    # (compact serde JSON, adjacently tagged, numeric user ids and string role ids), so
    # exact-match filters on the assignee property behave the same across all events.
    assignee_id = int(assignee["id"]) if assignee["type"] == "user" else str(assignee["id"])
    return json.dumps({"type": assignee["type"], "id": assignee_id}, separators=(",", ":"))


def current_assignee_property(issue: ErrorTrackingIssue) -> Optional[str]:
    assignment = ErrorTrackingIssueAssignment.objects.filter(issue_id=issue.id).only("user_id", "role_id").first()
    if assignment is None:
        return None
    if assignment.user_id:
        return assignee_property({"type": "user", "id": assignment.user_id})
    if assignment.role_id:
        return assignee_property({"type": "role", "id": assignment.role_id})
    return None
