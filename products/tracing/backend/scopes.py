"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="tracing",
        name="Tracing",
        plural="tracing",
        description="Distributed tracing spans and traces, saved views, retention, and service health and service map data.",
        group="Error tracking, logs & tracing",
        docs_url="https://posthog.com/docs/distributed-tracing/start-here",
    ),
)
