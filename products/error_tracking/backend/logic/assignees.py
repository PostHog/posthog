"""Issue assignee values for lifecycle events and alert notifications.

The Temporal lifecycle activities import this module, so it must not import the
Temporal package: that package loads every workflow module, which would make an
import cycle with logic/lifecycle_events.py.
"""

import json
from collections.abc import Collection, Sequence
from typing import Any
from uuid import UUID

from django.db.models import Exists, OuterRef

from posthog.dataclasses import frozen
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

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
    return resolve_current_assignees([issue_id]).get(UUID(str(issue_id)))


def resolve_current_assignees(issue_ids: Sequence[UUID | str]) -> dict[UUID, ResolvedAssignee]:
    """Current assignee of each issue, with display values, for issues that have one."""
    assignments = (
        ErrorTrackingIssueAssignment.objects.filter(issue_id__in=issue_ids)
        .select_related("user", "role")
        .only("issue_id", "user__first_name", "user__last_name", "user__email", "role__name")
        .annotate(
            user_is_member=Exists(
                OrganizationMembership.objects.filter(
                    user_id=OuterRef("user_id"), organization_id=OuterRef("issue__team__organization_id")
                )
            )
        )
    )
    resolved: dict[UUID, ResolvedAssignee] = {}
    for assignment in assignments:
        assignee = _resolve_assignment(assignment)
        if assignee is not None:
            resolved[assignment.issue_id] = assignee
    return resolved


def _resolve_assignment(assignment: ErrorTrackingIssueAssignment) -> ResolvedAssignee | None:
    if assignment.user is not None:
        return _resolve_user(
            assignment.user,
            is_member=assignment.user_is_member,  # type: ignore[attr-defined]  # annotated by resolve_current_assignees
        )
    if assignment.role is not None:
        return ResolvedAssignee(
            property_value=assignee_property({"type": "role", "id": assignment.role_id}),
            name=assignment.role.name,
            email=None,
        )
    return None


def _resolve_user(user: User, *, is_member: bool) -> ResolvedAssignee:
    property_value = assignee_property({"type": "user", "id": user.id})
    # Removing a member from the organization does not clear their assignments. Keep a
    # former member's name and email out of events that go to the organization's destinations.
    if not is_member:
        return ResolvedAssignee(property_value=property_value, name=None, email=None)
    return ResolvedAssignee(property_value=property_value, name=user.get_full_name() or user.email, email=user.email)


def resolve_user_assignees(organization_id: UUID, user_ids: Collection[int]) -> dict[int, ResolvedAssignee]:
    """Display values for users as assignees, whether or not they are assigned anywhere now."""
    member_ids = set(
        OrganizationMembership.objects.filter(organization_id=organization_id, user_id__in=user_ids).values_list(
            "user_id", flat=True
        )
    )
    return {
        user.id: _resolve_user(user, is_member=user.id in member_ids)
        for user in User.objects.filter(id__in=user_ids).only("id", "first_name", "last_name", "email")
    }
