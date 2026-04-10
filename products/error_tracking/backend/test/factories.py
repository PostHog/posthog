"""Sanctioned test-only factories for Error tracking ORM objects.

This module is the *only* public path through which external tests may
create Error tracking model instances. External code should never import
from ``products.error_tracking.backend.models`` directly — the module is
intentionally not on the tach interface list.

Keep these factories narrow. Add a builder only when a test needs one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
)

if TYPE_CHECKING:
    from posthog.models.team.team import Team
    from posthog.models.user import User


__all__ = [
    "create_issue",
    "create_issue_assignment",
    "create_issue_fingerprint",
]


def create_issue(
    *,
    team: Team,
    id: str | UUID | None = None,
    status: str = ErrorTrackingIssue.Status.ACTIVE,
    name: str | None = None,
    description: str | None = None,
) -> ErrorTrackingIssue:
    kwargs: dict[str, Any] = {"team": team, "status": status, "name": name, "description": description}
    if id is not None:
        kwargs["id"] = id
    return ErrorTrackingIssue.objects.create(**kwargs)


def create_issue_fingerprint(
    *,
    team: Team,
    issue: ErrorTrackingIssue,
    fingerprint: str,
    version: int = 1,
) -> ErrorTrackingIssueFingerprintV2:
    return ErrorTrackingIssueFingerprintV2.objects.create(
        team=team,
        issue=issue,
        fingerprint=fingerprint,
        version=version,
    )


def create_issue_assignment(
    *,
    team: Team,
    issue: ErrorTrackingIssue,
    user: User | None = None,
    role_id: str | UUID | None = None,
) -> ErrorTrackingIssueAssignment:
    return ErrorTrackingIssueAssignment.objects.create(
        team=team,
        issue=issue,
        user=user,
        role_id=role_id,
    )
