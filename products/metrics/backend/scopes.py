"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="metrics",
        name="Metrics",
        plural="metrics",
        description="Metrics, including PromQL queries, metric labels, and suggested or imported metrics dashboards.",
        group="Error tracking, logs & tracing",
        docs_url="https://posthog.com/docs/metrics",
    ),
)
