"""
Events retention settings for organizations and projects.

The periods set here are the ones the events cleanup deletes by, at every monthly cleanup. Projects without a period
keep events for their plan's default period, which the cleanup every 3 months deletes by.
"""

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User

from products.product_analytics.backend import events_retention
from products.product_analytics.backend.facade.contracts import OrganizationEventsRetention, ProjectEventsRetention


def organization_events_retention(organization: Organization) -> OrganizationEventsRetention:
    """The organization's window and the range its admins can set."""
    return events_retention.organization_events_retention(organization)


def project_events_retention(team: Team) -> ProjectEventsRetention:
    """The period set for this project and its next deletion."""
    return events_retention.project_events_retention(team)


def project_events_deleted_by_retention(team: Team, months: int) -> int:
    """How many of the project's events the monthly cleanup would delete now with this period. Cached."""
    return events_retention.project_events_deleted_by_retention(team, months)


def organization_events_deleted_by_retention(organization: Organization, months: int) -> int:
    """How many events the monthly cleanup would delete now from the projects that use the organization's period."""
    return events_retention.organization_events_deleted_by_retention(organization, months)


def set_organization_events_retention(
    organization: Organization, months: int | None, *, user: User, was_impersonated: bool
) -> None:
    """Set or clear the organization's window. Raises a Django ValidationError for a window outside the range."""
    events_retention.set_organization_events_retention(
        organization, months, user=user, was_impersonated=was_impersonated
    )


def set_project_events_retention(team: Team, months: int | None, *, user: User, was_impersonated: bool) -> None:
    """Set or clear the project's window. Raises a Django ValidationError for a window outside the range."""
    events_retention.set_project_events_retention(team, months, user=user, was_impersonated=was_impersonated)
