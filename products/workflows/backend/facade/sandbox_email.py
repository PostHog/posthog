"""The sandbox sender: PostHog's shared email sender for teams that haven't verified a domain yet."""

from products.workflows.backend.services.sandbox_email.provisioning import (
    SANDBOX_SENDER_ADOPTION_FLAG,
    SANDBOX_SENDER_INTEGRATION_ID,
    provision_sandbox_sender,
    sandbox_adoption_enabled,
    sandbox_sender_status,
)
from products.workflows.backend.services.sandbox_email.validation import (
    ADOPTION_UNAVAILABLE,
    SANDBOX_EMAIL_ACTION_TYPE,
    validate_sandbox_email_action,
)

__all__ = [
    "ADOPTION_UNAVAILABLE",
    "SANDBOX_EMAIL_ACTION_TYPE",
    "SANDBOX_SENDER_ADOPTION_FLAG",
    "SANDBOX_SENDER_INTEGRATION_ID",
    "provision_sandbox_sender",
    "sandbox_adoption_enabled",
    "sandbox_sender_status",
    "validate_sandbox_email_action",
]
