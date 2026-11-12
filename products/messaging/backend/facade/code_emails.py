"""Emails sent from code under a `template_key` with no template: list them, read one, and label it."""

from products.messaging.backend.models.transactional_email_key import SOURCE_URL_MAX_LENGTH
from products.messaging.backend.services.code_emails import get_code_email, list_code_emails, update_code_email

__all__ = ["SOURCE_URL_MAX_LENGTH", "get_code_email", "list_code_emails", "update_code_email"]
