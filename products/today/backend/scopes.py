"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="today",
        name="Today home",
        plural="Today home",
        description="The Today home page, including highlights, the key numbers you pin, and report excerpts.",
        group="AI & context management tools",
    ),
)
