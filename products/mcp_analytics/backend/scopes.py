"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="mcp_analytics",
        name="MCP analytics",
        plural="MCP analytics",
        description="MCP analytics sessions, tool calls, intent clusters, and feedback submitted for your MCP server.",
        group="LLM & MCP analytics",
        docs_url="https://posthog.com/docs/mcp-analytics",
    ),
)
