"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="posthog_support",
        name="PostHog Support tickets via MCP",
        plural="PostHog Support tickets via MCP",
        description="Agents can draft tickets to PostHog's support engineers on some topics, and open them only after you approve the draft.",
        group="Organization & account",
        docs_url="https://posthog.com/docs/support-options",
        actions=("write",),
    ),
)
