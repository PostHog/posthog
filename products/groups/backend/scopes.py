"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="group",
        name="Group",
        plural="groups",
        description="Group types and groups used in group analytics, including their properties.",
        group="Events, people & data model",
        docs_url="https://posthog.com/docs/product-analytics/group-analytics",
    ),
)
