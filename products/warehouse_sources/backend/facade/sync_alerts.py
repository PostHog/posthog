"""Warehouse alert destination vocabulary for the warehouse presentation endpoints, and what the
failure digest asks of warehouse alerts."""

from posthog.models import Team

from products.warehouse_sources.backend.sync_alerts import default_alert
from products.warehouse_sources.backend.sync_alerts.destinations import (
    EVENT_IDS,
    EVENT_KIND_CONFIG,
    WAREHOUSE_ALERT_DESTINATION_TYPES,
)

__all__ = [
    "EVENT_IDS",
    "EVENT_KIND_CONFIG",
    "WAREHOUSE_ALERT_DESTINATION_TYPES",
    "alerts_replace_failure_digest",
    "create_default_failure_alert",
]


def create_default_failure_alert(team: Team) -> None:
    """Give a project that just added a source its default sync failure email alert, unless it already
    had one, set up its own, or deleted the default. Never raises, so a source create cannot fail on it."""
    default_alert.ensure_default_failure_alert_safely(team)


def alerts_replace_failure_digest(team: Team) -> bool:
    """Whether the project's warehouse alerts already email its members about every failing source,
    so the daily failure digest would send the same news twice."""
    return default_alert.emails_replace_failure_digest(team)
