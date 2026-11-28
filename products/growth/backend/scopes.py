"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="posthog_support",
        name="PostHog Support tickets",
        plural="PostHog Support tickets",
        description="Agents can open support tickets on your behalf on some topics, and are told to ask you first.",
        group="Organization & account",
        docs_url="https://posthog.com/docs/support-options",
        actions=("write",),
    ),
)
