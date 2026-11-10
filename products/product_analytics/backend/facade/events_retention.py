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

NOT_A_STANDARD_PERIOD_MESSAGE = events_retention.NOT_A_STANDARD_PERIOD_MESSAGE


def organization_events_retention(organization: Organization) -> OrganizationEventsRetention:
    """The organization's period and the periods its admins can set."""
    return events_retention.organization_events_retention(organization)


def project_events_retention(team: Team) -> ProjectEventsRetention:
    """The period set for this project and its next deletion."""
    return events_retention.project_events_retention(team)


def project_events_deleted(team: Team, months: int, *, concurrency_slots: events_retention.ConcurrencySlots) -> int:
    return events_retention.project_events_deleted(team, months, concurrency_slots=concurrency_slots)


def organization_events_deleted(
    organization: Organization, months: int, *, concurrency_slots: events_retention.ConcurrencySlots
) -> int:
    return events_retention.organization_events_deleted(organization, months, concurrency_slots=concurrency_slots)


def organization_downgrade_events_deleted(
    organization: Organization, months: int, *, concurrency_slots: events_retention.ConcurrencySlots
) -> int:
    return events_retention.organization_downgrade_events_deleted(
        organization, months, concurrency_slots=concurrency_slots
    )


def set_organization_events_retention(
    organization: Organization,
    months: int | None,
    *,
    user: User,
    was_impersonated: bool,
    analytics_properties: dict[str, object] | None = None,
) -> None:
    """Set or clear the organization's period. Raises a Django ValidationError for a period its admins can't set."""
    events_retention.set_organization_events_retention(
        organization, months, user=user, was_impersonated=was_impersonated, analytics_properties=analytics_properties
    )


def set_project_events_retention(
    team: Team,
    months: int | None,
    *,
    user: User,
    was_impersonated: bool,
    analytics_properties: dict[str, object] | None = None,
) -> None:
    """Set or clear the project's period. Raises a Django ValidationError for a period its admins can't set."""
    events_retention.set_project_events_retention(
        team, months, user=user, was_impersonated=was_impersonated, analytics_properties=analytics_properties
    )
