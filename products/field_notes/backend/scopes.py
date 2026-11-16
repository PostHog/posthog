"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="field_note",
        name="Field note",
        plural="field notes",
        description="Field notes left on your site with the toolbar, including creating, updating, and resolving them.",
        group="AI & context management tools",
        docs_url="https://posthog.com/docs/toolbar",
    ),
)
