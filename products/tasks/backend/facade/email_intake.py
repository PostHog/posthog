"""Facade for starting tasks from inbound email. Consumed by the conversations product's Mailgun webhook."""

from products.tasks.backend.logic.services.email_intake import (
    EmailTaskIntake,
    InboundTaskEmail,
    clear_inbox_address,
    ensure_inbox_address,
    extract_inbox_token,
    find_team_by_inbox_token,
    get_inbox_address,
    is_inbound_email_configured,
    start_task_from_email,
)

__all__ = [
    "EmailTaskIntake",
    "InboundTaskEmail",
    "clear_inbox_address",
    "ensure_inbox_address",
    "extract_inbox_token",
    "find_team_by_inbox_token",
    "get_inbox_address",
    "is_inbound_email_configured",
    "start_task_from_email",
]
