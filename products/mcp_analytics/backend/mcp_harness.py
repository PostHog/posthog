"""Canonical harness (MCP client) labelling, shared by every backend query runner.

A "harness" is the friendly product label for the MCP client that made a call —
"Claude Agent SDK", "OpenAI Codex", "Cursor", … An event carries only raw,
self-reported identity signals; resolving them to a label is a two-step,
query-time computation:

  1. Resolve a normalized token from the strongest available signal (the
     x-anthropic-client vendor header, then Claude Code's User-Agent surface,
     then the Grok User-Agent surface,
     then the clientInfo.name — `$mcp_client_name` as reported by the posthog-node
     MCP analytics SDK, or `mcp_session_client_name` as reported by PostHog's hosted
     MCP server — then the User-Agent product token, then the OAuth client name) —
     `HARNESS_TOKEN_SQL`.
  2. Bucket that token into a customer label — `harness_label_sql` when the result must
     stay inside `HARNESS_LABELS`, or `harness_label_or_token_sql` when an unrecognized
     client is better named by its own self-report than collapsed into "Other".

Read the token, never a raw property: `$mcp_client_name` is absent on every call that
isn't the session's `initialize`, so anything grouping on it alone leaves the bulk of
traffic unattributed.

This module is the single source of truth for harness classification. The frontend no
longer classifies — `products/mcp_analytics/frontend/dashboard/harnessRegistry.ts` keeps
only a label-to-logo/colour map (`HARNESS_BY_LABEL`), keyed by the labels this module
emits, and a cross-language test pins those keys to `HARNESS_LABELS`. Two documented
copies must move in lockstep: the query in the `querying-posthog-data` skill's
`models-mcp.md`, and the vocabulary table in this product's `debugging-mcp-analytics`
skill.

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

# The ordered resolution steps, mirroring HARNESS_ROWS_QUERY in the frontend.
_RAW_TOKEN = f"""coalesce(
    multiIf(
        lower(toString(properties.mcp_vendor_client)) = 'claudecode', 'claude-code',
        lower(toString(properties.mcp_vendor_client)) = 'claudeai', 'claude-ai',
        lower(toString(properties.mcp_vendor_client)) = 'cowork', 'cowork',
        lower(toString(properties.mcp_vendor_client)) = 'claudedesign', 'claude-design',
        NULL
    ),
    if(lower({_UA_PRODUCT}) = 'claude-code', {_UA_TOKEN}, NULL),
    -- grok.com Connectors self-identifies as grok only in the User-Agent
    -- (`grok-connectors-manager/…`); its clientInfo.name is the generic
    -- "connectors-manager", which would otherwise win below and drop the vendor.
    -- Promote the grok UA above it. (grok-shell keeps its `grok-`-prefixed
    -- clientInfo.name and buckets to Grok without help.)
    if(startsWith(lower({_UA_PRODUCT}), 'grok'), {_UA_TOKEN}, NULL),
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

# The same resolution and proxy-suffix strip, but with the client's own capitalization
# intact, so an unrecognized client can be shown under the name it actually reported
# rather than a lower-cased one. Matching still uses the token above; this is display
# only. `(?i)` does the case-insensitive strip that `lower()` made unnecessary there.
HARNESS_DISPLAY_NAME_SQL = f"trim(replaceRegexpAll({_RAW_TOKEN}, '(?i)\\\\s*\\\\(via mcp-remote[^)]*\\\\)\\\\s*', ''))"

# Shown by `harness_label_or_token_sql` when an event carries no identity signal at
# all — not a client anyone runs, unlike every other label this module emits.
UNIDENTIFIED_HARNESS_LABEL = "Unidentified client"

# Tokens are self-reported and unbounded; cap one before it can widen a grouping key.
_MAX_TOKEN_LABEL_LENGTH = 200


def harness_label_sql(token_col: str = "h") -> str:
    """Bucket a normalized harness token column into a customer label.

    Every unrecognized token collapses into "Other", so the result is always one of
    `HARNESS_LABELS`. Callers that aggregate labels into a per-row array need that
    bound; callers that rank a top-N list should prefer `harness_label_or_token_sql`,
    which names an unrecognized client instead of discarding it.

    `token_col` is the name of a column already holding `HARNESS_TOKEN_SQL`
    (or an argMax of it) — pass the alias, not the token expression itself.
    Surface-specific entries are listed before the generic prefix matches so
    `find`-style first-match precedence matches the frontend registry order.
    """
    return _label_multi_if(token_col, "'Other'")


def harness_label_or_token_sql(token_col: str = "h", display_col: str = "client_display") -> str:
    """Same bucketing as `harness_label_sql`, but names unrecognized clients verbatim.

    An unrecognized token is not noise — it is the client's own self-reported name
    ("posthog-attribution-service", "openclaw-bundle-mcp"), which is strictly more
    useful in a ranked list of callers than "Other". `display_col` holds
    `HARNESS_DISPLAY_NAME_SQL` so that name keeps its own capitalization; matching still
    happens on the lower-cased `token_col`. The name is event-supplied and unbounded, so
    it is capped before it can reach a grouping key. Only a genuinely identity-free event
    (the empty token) falls through to a placeholder.

    Unlike `harness_label_sql`, the result is NOT confined to `HARNESS_LABELS` — never
    use this where labels accumulate into an array or an unbounded GROUP BY.
    """
    if not display_col.isidentifier():
        raise ValueError(f"display_col must be a SQL identifier, got {display_col!r}")
    fallback = (
        f"if({token_col} = '', '{UNIDENTIFIED_HARNESS_LABEL}', substring({display_col}, 1, {_MAX_TOKEN_LABEL_LENGTH}))"
    )
    return _label_multi_if(token_col, fallback)


def _label_multi_if(token_col: str, fallback_sql: str) -> str:
    """The shared bucketing `multiIf`, parameterized by its final (else) arm.

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
        -- Codex reports itself two ways: `codex-mcp-client` as its clientInfo.name, and
        -- the `openai-mcp/… (Codex)` User-Agent surface. The surface has to be matched
        -- before the generic `openai-mcp` prefix below, and the `codex` prefix further
        -- down can never catch it, so both spellings need their own branch.
        {token_col} = 'openai-mcp codex', 'OpenAI Codex',
        startsWith({token_col}, 'openai-mcp'), 'OpenAI',
        startsWith({token_col}, 'codex'), 'OpenAI Codex',
        startsWith({token_col}, 'grok'), 'Grok',
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
        -- PostHog's own CLI (`services/mcp/src/cli/context.ts` hard-codes this name).
        -- It is a wrapper, not a terminal client: agents are told to shell out to it by
        -- the AGENTS.md snippet it installs, and it forwards no identity for whoever
        -- invoked it, so these calls can only ever be attributed to the CLI itself.
        {token_col} = 'posthog-cli', 'PostHog CLI',
        {fallback_sql}
    )"""


# Every customer label `harness_label_sql` can emit. A unit test asserts this tuple
# stays in step with the multiIf branches; the frontend registry's logo/colour keys
# are cross-checked against it when the dashboard is rewired onto this runner.
# `harness_label_or_token_sql` can also emit a raw token or UNIDENTIFIED_HARNESS_LABEL.
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
    "Grok",
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
    "PostHog CLI",
    "Other",
)
