"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="transactional_email",
        name="Transactional email",
        plural="transactional emails",
        description="Making a template transactional and sending email from it, and reading a sent email's status with a project secret key.",
        group="Messaging",
        docs_url="https://posthog.com/docs/workflows/transactional-emails",
    ),
    ScopeDoc(
        object="transactional_push",
        name="Transactional push notification",
        plural="transactional push notifications",
        description="Sending a push notification from a push template made transactional with a project secret key.",
        group="Messaging",
        docs_url="https://posthog.com/docs/workflows/push-notifications",
    ),
)
