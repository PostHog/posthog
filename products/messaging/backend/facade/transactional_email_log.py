"""The transactional email log: every send of a project, its timeline, and its delivery stats."""

from products.messaging.backend.models.email_status_sql import EMAIL_STATUS_RETENTION_DAYS
from products.messaging.backend.services.transactional_email_log import (
    MAX_CONVERSION_WINDOW_DAYS,
    find_sends_by_provider_message_ids,
    get_transactional_email,
    list_transactional_emails,
    transactional_email_results,
    transactional_email_stats,
    transactional_email_stats_over_time,
)

__all__ = [
    "EMAIL_STATUS_RETENTION_DAYS",
    "MAX_CONVERSION_WINDOW_DAYS",
    "find_sends_by_provider_message_ids",
    "get_transactional_email",
    "list_transactional_emails",
    "transactional_email_results",
    "transactional_email_stats",
    "transactional_email_stats_over_time",
]
