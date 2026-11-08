"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="product_tour",
        name="Product tour",
        plural="product tours",
        description="Product tours, including their steps, targeting, drafts, and publishing.",
        group="Feature flags, experiments & surveys",
    ),
)
