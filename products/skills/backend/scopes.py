"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="llm_skill",
        name="LLM skill",
        plural="LLM skills",
        description="Skills for AI agents with their files and versions, the skills marketplace, and PostHog Review skill settings.",
        group="LLM & MCP analytics",
        docs_url="https://posthog.com/docs/skills",
    ),
)
