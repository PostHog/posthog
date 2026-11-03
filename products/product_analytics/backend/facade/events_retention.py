"""
Events retention settings for organizations and projects.

The windows set here are the ones the monthly events cleanup deletes by, so a saved window deletes events.
"""

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User

from products.product_analytics.backend import events_retention
from products.product_analytics.backend.facade.contracts import OrganizationEventsRetention


def organization_events_retention(organization: Organization) -> OrganizationEventsRetention:
    """The organization's window and the range its admins can set."""
    return events_retention.organization_events_retention(organization)


def project_events_retention_months(team: Team) -> int | None:
    """The window set for this project, or None while it uses the organization's window."""
    return events_retention.project_events_retention_months(team)


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
