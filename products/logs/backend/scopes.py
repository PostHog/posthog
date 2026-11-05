"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="logs",
        name="Logs",
        plural="logs",
        description="Logs, including queries, saved views, alerts, and sampling, retention, and log-to-metric rules.",
        group="Error tracking, logs & tracing",
        docs_url="https://posthog.com/docs/logs",
    ),
)
