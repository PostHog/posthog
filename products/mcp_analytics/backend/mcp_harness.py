"""Canonical harness (MCP client) labelling, shared by every backend query runner.

A "harness" is the friendly product label for the MCP client that made a call —
"Claude Agent SDK", "OpenAI Codex", "Cursor", … An event carries only raw,
self-reported identity signals; resolving them to a label is a two-step,
query-time computation:

  1. Resolve a normalized token from the strongest available signal (the
     x-anthropic-client vendor header, then Claude Code's User-Agent surface,
     then the clientInfo.name — `$mcp_client_name` as reported by the posthog-node
     MCP analytics SDK, or `mcp_session_client_name` as reported by PostHog's hosted
     MCP server — then the User-Agent product token, then the OAuth client name) —
     `HARNESS_TOKEN_SQL`.
  2. Bucket that token into a customer label — `harness_label_sql`.

This module is the single source of truth for harness classification. The frontend no
longer classifies — `products/mcp_analytics/frontend/dashboard/harnessRegistry.ts` keeps
only a label-to-logo/colour map (`HARNESS_BY_LABEL`), keyed by the labels this module
emits, and a cross-language test pins those keys to `HARNESS_LABELS`. The one remaining
copy that must move in lockstep is the documented query in the `querying-posthog-data`
skill's `models-mcp.md`.

Because the token appears many times in the bucketing `multiIf`, callers compute
it once as a column (`{HARNESS_TOKEN_SQL} AS h`, or `argMax(..., timestamp)` for a
per-session value) and pass that column name to `harness_label_sql` — never inline
the token into the `multiIf`. `token_col` is always a SQL identifier the caller
controls, never request input.
"""

# Leading product token of the User-Agent, e.g. "claude-code" from "claude-code/2.1.x (cli)".
_UA_PRODUCT = "extract(toString(properties.$mcp_client_user_agent), '^([^/]+)')"

# Product token + first parenthetical (the surface) with the version dropped,
# e.g. "claude-code cli", "openai-mcp chatgpt". Used both gated to claude-code
# (step 2, to keep the CLI/SDK/IDE split) and as the generic fallback (step 4).
_UA_TOKEN = f"trim(concat({_UA_PRODUCT}, ' ', extract(toString(properties.$mcp_client_user_agent), '[(]([^,)]+)')))"

# Step 1-5 of the resolution, mirroring HARNESS_ROWS_QUERY in the frontend.
_RAW_TOKEN = f"""coalesce(
    multiIf(
        lower(toString(properties.mcp_vendor_client)) = 'claudecode', 'claude-code',
        lower(toString(properties.mcp_vendor_client)) = 'claudeai', 'claude-ai',
        lower(toString(properties.mcp_vendor_client)) = 'cowork', 'cowork',
        lower(toString(properties.mcp_vendor_client)) = 'claudedesign', 'claude-design',
        NULL
    ),
    if(lower({_UA_PRODUCT}) = 'claude-code', {_UA_TOKEN}, NULL),
    nullIf(nullIf(toString(properties.$mcp_client_name), ''), 'mcp'),
    nullIf(nullIf(toString(properties.mcp_session_client_name), ''), 'mcp'),
    nullIf({_UA_TOKEN}, ''),
    nullIf(toString(properties.$mcp_oauth_client_name), ''),
    ''
)"""

# The normalized token: lower-cased first, then the "(via mcp-remote …)" proxy
# suffix stripped and trimmed, matching categorizeHarness's normalization so the
# bucketing comparisons below are case- and proxy-insensitive. Lower-casing before
# the strip keeps the pattern case-flag-free; the doubled backslashes survive HogQL
# string parsing to reach RE2 as `\s` / `\(`.
HARNESS_TOKEN_SQL = f"trim(replaceRegexpAll(lower({_RAW_TOKEN}), '\\\\s*\\\\(via mcp-remote[^)]*\\\\)\\\\s*', ''))"


def harness_label_sql(token_col: str = "h") -> str:
    """Bucket a normalized harness token column into a customer label.

    `token_col` is the name of a column already holding `HARNESS_TOKEN_SQL`
    (or an argMax of it) — pass the alias, not the token expression itself.
    Surface-specific entries are listed before the generic prefix matches so
    `find`-style first-match precedence matches the frontend registry order.

    `token_col` is interpolated into SQL, so it must be a bare identifier — never
    request input. The guard makes that impossible to violate by accident.
    """
    if not token_col.isidentifier():
        raise ValueError(f"token_col must be a SQL identifier, got {token_col!r}")
    return f"""multiIf(
        {token_col} = 'claude-code claude-desktop', 'Claude Desktop',
        {token_col} = 'claude-code claude-vscode', 'Claude Code (VS Code)',
        startsWith({token_col}, 'claude-code sdk'), 'Claude Agent SDK',
        startsWith({token_col}, 'claude-code'), 'Claude Code',
        {token_col} IN ('claude-ai', 'anthropic/claudeai', 'claude-user'), 'Claude.ai',
        {token_col} = 'anthropic/api', 'Anthropic API',
        {token_col} = 'cowork', 'Cowork',
        {token_col} = 'claude-design', 'Claude Design',
        {token_col} = 'openai-mcp chatgpt', 'ChatGPT',
        {token_col} = 'openai-mcp agent builder', 'OpenAI Agent Builder',
        {token_col} = 'openai-mcp responses api', 'OpenAI Responses API',
        startsWith({token_col}, 'openai-mcp'), 'OpenAI',
        startsWith({token_col}, 'codex'), 'OpenAI Codex',
        startsWith({token_col}, 'cursor'), 'Cursor',
        startsWith({token_col}, 'visual studio code'), 'VS Code',
        {token_col} = 'windsurf', 'Windsurf',
        startsWith({token_col}, 'replit'), 'Replit',
        startsWith({token_col}, 'lovable'), 'Lovable',
        {token_col} = 'manus', 'Manus',
        {token_col} = 'coderabbit', 'CodeRabbit',
        startsWith({token_col}, 'notion'), 'Notion',
        startsWith({token_col}, 'linear'), 'Linear',
        position({token_col}, 'librechat') > 0, 'LibreChat',
        startsWith({token_col}, 'pi-client'), 'Pi',
        startsWith({token_col}, 'antigravity'), 'Antigravity',
        {token_col} = 'poke', 'Poke',
        {token_col} = 'opencode', 'opencode',
        startsWith({token_col}, 'kiro'), 'Kiro',
        startsWith({token_col}, 'desktop-commander'), 'Desktop Commander',
        'Other'
    )"""


# Every customer label `harness_label_sql` can emit. A unit test asserts this tuple
# stays in step with the multiIf branches; the frontend registry's logo/colour keys
# are cross-checked against it when the dashboard is rewired onto this runner.
HARNESS_LABELS: tuple[str, ...] = (
    "Claude Desktop",
    "Claude Code (VS Code)",
    "Claude Agent SDK",
    "Claude Code",
    "Claude.ai",
    "Anthropic API",
    "Cowork",
    "Claude Design",
    "ChatGPT",
    "OpenAI Agent Builder",
    "OpenAI Responses API",
    "OpenAI",
    "OpenAI Codex",
    "Cursor",
    "VS Code",
    "Windsurf",
    "Replit",
    "Lovable",
    "Manus",
    "CodeRabbit",
    "Notion",
    "Linear",
    "LibreChat",
    "Pi",
    "Antigravity",
    "Poke",
    "opencode",
    "Kiro",
    "Desktop Commander",
    "Other",
)
