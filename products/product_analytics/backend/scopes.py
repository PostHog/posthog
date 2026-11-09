"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="insight",
        name="Insight",
        plural="insights",
        description="Insights, including their queries, results, and explanations, plus anomaly rates for trends insights.",
        group="Product analytics",
        docs_url="https://posthog.com/docs/product-analytics/insights",
    ),
    ScopeDoc(
        object="insight_variable",
        name="Insight variable",
        plural="insight variables",
        description="SQL variables that insights and dashboards can reference and override.",
        group="Product analytics",
        docs_url="https://posthog.com/docs/data-warehouse/sql/variables",
    ),
)
