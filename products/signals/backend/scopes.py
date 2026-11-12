"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="inbox",
        name="Inbox",
        plural="inbox reports",
        description="Inbox reports with their checks and artifacts, signal source settings, and signal processing controls.",
        group="AI & context management tools",
        docs_url="https://posthog.com/docs/self-driving/inbox",
    ),
    ScopeDoc(
        object="signal_scout",
        name="Signals agent",
        plural="signals agents",
        description="Self-driving scouts, including their configuration, runs, findings, notes, memories, and suggested scouts.",
        group="AI & context management tools",
        docs_url="https://posthog.com/docs/self-driving/scouts",
    ),
    ScopeDoc(
        object="signal_usage",
        name="Self-driving usage",
        plural="self-driving usage",
        description="Self-driving usage over the last 30 days, broken down by scout and by signal source.",
        group="AI & context management tools",
        docs_url="https://posthog.com/docs/self-driving/pricing",
        actions=("read",),
    ),
)
