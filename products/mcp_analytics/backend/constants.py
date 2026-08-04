# Key on this canonical event only — also matching the legacy `mcp_tool_call` alias
# (frozen, pre-2026-06-16 history) would double-count every call.
MCP_TOOL_CALL_EVENT = "$mcp_tool_call"
MCP_MISSING_CAPABILITY_EVENT = "$mcp_missing_capability"

# The canonical MCP session id: properties.$mcp_session_id when the SDK set it, falling
# back to the materialised $session_id column otherwise. Mirrors
# tool_tables._CONVERSATION_ID — clients that only stamp $mcp_session_id (the documented
# grouping key; see MCPSessionSerializer.session_id help_text) would otherwise group into
# zero or fragmented sessions in queries that key on the bare $session_id column alone.
SESSION_ID_EXPR = "coalesce(nullIf(toString(properties.$mcp_session_id), ''), toString($session_id))"
