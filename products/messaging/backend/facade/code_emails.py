"""Emails sent from code under a `template_key` with no template: list them, read one, label it, and find the file
that sends it."""

from products.messaging.backend.models.transactional_email_key import SOURCE_URL_MAX_LENGTH
from products.messaging.backend.services.code_email_source import find_source_candidates, source_detection_enabled
from products.messaging.backend.services.code_emails import get_code_email, list_code_emails, update_code_email

__all__ = [
    "SOURCE_URL_MAX_LENGTH",
    "find_source_candidates",
    "get_code_email",
    "list_code_emails",
    "source_detection_enabled",
    "update_code_email",
]
