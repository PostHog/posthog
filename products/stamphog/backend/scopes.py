"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="stamphog",
        name="Stamphog",
        plural="stamphog",
        description="Stamphog pull request approvals, including repository settings, review runs, reviewer routing, and digests.",
        group="Developer experience",
    ),
)
