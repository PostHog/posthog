"""The transactional email log: every send of a project, its timeline, and its delivery stats."""

from products.messaging.backend.models.email_status_sql import EMAIL_STATUS_RETENTION_DAYS
from products.messaging.backend.services.transactional_email_activity import (
    ACTIVITY_WINDOW_DAYS,
    get_transactional_email_activity,
)
from products.messaging.backend.services.transactional_email_log import (
    MAX_CONVERSION_WINDOW_DAYS,
    get_transactional_email,
    list_transactional_emails,
    transactional_email_results,
    transactional_email_stats,
    transactional_email_stats_over_time,
)

__all__ = [
    "ACTIVITY_WINDOW_DAYS",
    "EMAIL_STATUS_RETENTION_DAYS",
    "MAX_CONVERSION_WINDOW_DAYS",
    "get_transactional_email",
    "get_transactional_email_activity",
    "list_transactional_emails",
    "transactional_email_results",
    "transactional_email_stats",
    "transactional_email_stats_over_time",
]
