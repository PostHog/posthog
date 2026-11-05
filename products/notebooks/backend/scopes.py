"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="notebook",
        name="Notebook",
        plural="notebooks",
        description="Notebooks and the reusable widgets you can embed in them.",
        group="Product analytics",
        docs_url="https://posthog.com/docs/notebooks",
    ),
)
