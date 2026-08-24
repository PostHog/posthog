# Key on this canonical event only — also matching the legacy `mcp_tool_call` alias
# (frozen, pre-2026-06-16 history) would double-count every call.
MCP_TOOL_CALL_EVENT = "$mcp_tool_call"
MCP_MISSING_CAPABILITY_EVENT = "$mcp_missing_capability"
# Emitted per tools/list response; carries $mcp_listed_tool_names (the advertised catalog).
MCP_TOOLS_LIST_EVENT = "$mcp_tools_list"

# Intent cluster snapshots are stored as one JSON blob and served unpaginated,
# so cap how many clusters (ranked by call volume) a snapshot carries. A
# degenerate clustering run can label nearly every intent as its own cluster —
# hundreds of near-singleton clusters make a multi-MB payload the UI then has
# to render in one go. Lives here (not intent_clustering.py) so the API read
# path can import it without pulling sklearn/numpy into the request path.
MAX_SNAPSHOT_CLUSTERS = 100

# Shown in the UI and stored on a failed snapshot, so both the interactive trigger and a
# scheduled run explain the same next step. Clustering embeds every intent, and the embedding
# worker drops requests from organizations that haven't consented to AI data processing.
AI_CONSENT_REQUIRED_MESSAGE = (
    "Clustering needs AI data processing approved for this organization. "
    "Enable it in organization settings, then run clustering again."
)
