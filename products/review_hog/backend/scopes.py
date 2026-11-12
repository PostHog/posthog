"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="review_hog",
        name="PostHog Review",
        plural="PostHog Review reviews",
        description="PostHog Review code reviews of your pull requests, plus repository settings and per-user review choices.",
        group="AI & context management tools",
    ),
)
