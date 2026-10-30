"""
Events retention settings for organizations and projects.

The windows set here are the ones the events cleanup deletes by: at every monthly cleanup when set to delete monthly,
else at the cleanup every 3 months.
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
    """The window set for this project, whether the project's window deletes monthly, and its next deletion."""
    return events_retention.project_events_retention(team)


def set_organization_events_retention(
    organization: Organization, months: int | None, delete_monthly: bool, *, user: User, was_impersonated: bool
) -> None:
    """Set or clear the organization's window. Raises a Django ValidationError for a window outside the range."""
    events_retention.set_organization_events_retention(
        organization, months, delete_monthly, user=user, was_impersonated=was_impersonated
    )


def set_project_events_retention(
    team: Team, months: int | None, delete_monthly: bool, *, user: User, was_impersonated: bool
) -> None:
    """Set or clear the project's window. Raises a Django ValidationError for a window outside the range."""
    events_retention.set_project_events_retention(
        team, months, delete_monthly, user=user, was_impersonated=was_impersonated
    )
