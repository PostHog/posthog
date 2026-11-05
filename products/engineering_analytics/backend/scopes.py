"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="engineering_analytics",
        name="Engineering analytics",
        plural="engineering analytics",
        description="Engineering analytics for connected GitHub repos: pull requests, CI runs, deploys, DORA metrics, and settings.",
        group="Developer experience",
    ),
)
