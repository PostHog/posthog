"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="error_tracking",
        name="Error tracking",
        plural="error tracking",
        description="Error tracking issues, releases, symbol sets, alerts, and grouping, assignment, and suppression rules.",
        group="Error tracking, logs & tracing",
        docs_url="https://posthog.com/docs/error-tracking",
    ),
)
