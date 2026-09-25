"""Issue assignee values for lifecycle events and alert notifications.

The Temporal lifecycle activities import this module, so it must not import the
Temporal package: that package loads every workflow module, which would make an
import cycle with logic/lifecycle_events.py.
"""

import json
from typing import Any
from uuid import UUID

from posthog.dataclasses import frozen

from products.error_tracking.backend.models import ErrorTrackingIssueAssignment


def assignee_property(assignee: dict[str, Any]) -> str:
    # Wire-compatible with cymbal's `Assignee` serialization on created/reopened events
    # (compact serde JSON, adjacently tagged, numeric user ids and string role ids), so
    # exact-match filters on the assignee property behave the same across all events.
    assignee_id = int(assignee["id"]) if assignee["type"] == "user" else str(assignee["id"])
    return json.dumps({"type": assignee["type"], "id": assignee_id}, separators=(",", ":"))


@frozen
class ResolvedAssignee:
    property_value: str
    name: str
    email: str | None

    def display_properties(self) -> dict[str, str]:
        properties = {"assignee_name": self.name}
        if self.email:
            properties["assignee_email"] = self.email
        return properties


def resolve_current_assignee(issue_id: UUID | str) -> ResolvedAssignee | None:
    assignment = (
        ErrorTrackingIssueAssignment.objects.filter(issue_id=issue_id)
        .select_related("user", "role")
        .only("user__first_name", "user__last_name", "user__email", "role__name")
        .first()
    )
    if assignment is None:
        return None
    if assignment.user is not None:
        user = assignment.user
        return ResolvedAssignee(
            property_value=assignee_property({"type": "user", "id": user.id}),
            name=user.get_full_name() or user.email,
            email=user.email,
        )
    if assignment.role is not None:
        return ResolvedAssignee(
            property_value=assignee_property({"type": "role", "id": assignment.role_id}),
            name=assignment.role.name,
            email=None,
        )
    return None
