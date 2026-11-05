"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="transactional_email",
        name="Transactional email",
        plural="transactional emails",
        description="Sending transactional email from a template and reading a sent email's status, without editing templates.",
        group="Messaging",
        docs_url="https://posthog.com/docs/workflows/transactional-emails",
    ),
)
