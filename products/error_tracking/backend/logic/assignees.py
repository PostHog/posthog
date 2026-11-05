"""Issue assignee values for lifecycle events and alert notifications.

The Temporal lifecycle activities import this module, so it must not import the
Temporal package: that package loads every workflow module, which would make an
import cycle with logic/lifecycle_events.py.
"""

import json
from typing import Any
from uuid import UUID

from django.db.models import Exists, OuterRef

from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.error_tracking.backend.models import ErrorTrackingIssueAssignment


def assignee_property(assignee: dict[str, Any]) -> str:
    # Wire-compatible with cymbal's `Assignee` serialization on created/reopened events
    # (compact serde JSON, adjacently tagged, numeric user ids and string role ids), so
    # exact-match filters on the assignee property behave the same across all events.
    assignee_id = int(assignee["id"]) if assignee["type"] == "user" else str(assignee["id"])
    return json.dumps({"type": assignee["type"], "id": assignee_id}, separators=(",", ":"))


def error_tracking_viewer_ids(*, user_ids: list[int], team_id: int) -> set[int]:
    """The users among `user_ids` who can view error tracking in the team.

    Raises when the access check fails, so each caller chooses how to fail closed.
    """
    if not user_ids:
        return set()
    access_by_user = UserAccessControl.for_user_ids(user_ids=user_ids, team=Team.objects.get(id=team_id))
    sample = next(iter(access_by_user.values()), None)
    if sample is not None and not sample.access_controls_supported:
        return set(user_ids)
    return {
        user_id
        for user_id, access in access_by_user.items()
        if access.check_access_level_for_resource("error_tracking", "viewer")
    }


@frozen
class ResolvedAssignee:
    property_value: str
    name: str | None
    email: str | None

    def display_properties(self) -> dict[str, str]:
        properties: dict[str, str] = {}
        if self.name:
            properties["assignee_name"] = self.name
        if self.email:
            properties["assignee_email"] = self.email
        return properties


def resolve_current_assignee(issue_id: UUID | str) -> ResolvedAssignee | None:
    assignment = (
        ErrorTrackingIssueAssignment.objects.filter(issue_id=issue_id)
        .select_related("user", "role")
        .only("user__first_name", "user__last_name", "user__email", "role__name")
        .annotate(
            user_is_member=Exists(
                OrganizationMembership.objects.filter(
                    user_id=OuterRef("user_id"), organization_id=OuterRef("issue__team__organization_id")
                )
            )
        )
        .first()
    )
    if assignment is None:
        return None
    if assignment.user is not None:
        user = assignment.user
        property_value = assignee_property({"type": "user", "id": user.id})
        # Removing a member from the organization does not clear their assignments. Keep a
        # former member's name and email out of events that go to the organization's destinations.
        if not assignment.user_is_member:
            return ResolvedAssignee(property_value=property_value, name=None, email=None)
        return ResolvedAssignee(
            property_value=property_value,
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
