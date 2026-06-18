# The @posthog/mcp SDK and PostHog's own MCP server both emit this canonical,
# $-prefixed event. PostHog's server additionally dual-emits a legacy `mcp_tool_call`
# alias for older dashboards; reading both names would double-count its calls, so we
# key on the canonical name only.
MCP_TOOL_CALL_EVENT = "$mcp_tool_call"
