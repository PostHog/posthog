"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="marketing_analytics",
        name="Marketing analytics",
        plural="marketing analytics",
        description="Marketing analytics conversion goals, marketing data sources, UTM audits, and conversion recordings.",
        group="Web, marketing & revenue analytics",
        docs_url="https://posthog.com/docs/web-analytics/marketing-analytics",
    ),
)
