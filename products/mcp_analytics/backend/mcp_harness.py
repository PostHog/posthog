"""Canonical harness (MCP client) labelling, shared by every backend query runner.

A "harness" is the friendly product label for the MCP client that made a call —
"Claude Agent SDK", "OpenAI Codex", "Cursor", … An event carries only raw,
self-reported identity signals; resolving them to a label is a two-step,
query-time computation:

  1. Resolve a normalized token from the strongest available signal, over exactly
     three properties — the ones the `@posthog/mcp` / `posthog.mcp` SDK schemas can
     emit: the x-anthropic-client vendor header (`$mcp_vendor_client`, with the
     legacy server-stamped `mcp_vendor_client` as a fallback for historical rows),
     then Claude Code's User-Agent surface, then the PostHog Wizard User-Agent, then the
     User-Agents in `_UA_FIRST_PRODUCTS`, then the clientInfo.name (`$mcp_client_name`),
     then the generic User-Agent product token (`$mcp_client_user_agent`) — `HARNESS_TOKEN_SQL`.
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
`models-mcp.md`, and the vocabulary table in `.agents/skills/debugging-mcp-analytics/`
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

# The x-anthropic-client vendor header, coalesced across both wire keys it is
# captured under: `$mcp_vendor_client` (the SDK name) and the unprefixed
# `mcp_vendor_client` (PostHog's own server). The unprefixed arm is load-bearing,
# not cosmetic: rows carrying only it often self-report a wrong clientInfo.name
# (Claude Code as "Anthropic/ClaudeAI"), so without it they misattribute.
_VENDOR = (
    "lower(coalesce(nullIf(toString(properties.$mcp_vendor_client), ''),"
    " nullIf(toString(properties.mcp_vendor_client), '')))"
)

# Clients whose User-Agent names them while their clientInfo.name is generic or
# belongs to the library they are built on, so the UA must outrank the name:
# - grok.com Connectors reports "connectors-manager" (grok-shell keeps a `grok-`
#   prefixed name and buckets without help).
# - Kimchi (kimchi.dev) is built on pi and reports pi-mcp's `pi-mcp-<server>`.
# - Devin reports the Rust SDK's default `rmcp`.
# - Cloudflare's MCP server portals report "mcp-client".
# - opencode's CLI can report "cli".
_UA_FIRST_PRODUCTS = ("grok", "kimchi", "devin", "cloudflare-mcp-portal", "opencode")
_UA_FIRST = " OR ".join(f"startsWith(lower({_UA_PRODUCT}), '{product}')" for product in _UA_FIRST_PRODUCTS)

# The ordered resolution steps: vendor header, then the User-Agent surfaces that
# outrank clientInfo.name, then clientInfo.name, then the generic UA token.
_RAW_TOKEN = f"""coalesce(
    multiIf(
        -- The header is captured verbatim and its value arrives in both spellings
        -- ('ClaudeCode' and 'claude-code'), so each vendor matches both.
        {_VENDOR} IN ('claudecode', 'claude-code'), 'claude-code',
        {_VENDOR} IN ('claudeai', 'claude-ai'), 'claude-ai',
        {_VENDOR} = 'cowork', 'cowork',
        {_VENDOR} IN ('claudedesign', 'claude-design'), 'claude-design',
        NULL
    ),
    if(lower({_UA_PRODUCT}) = 'claude-code', {_UA_TOKEN}, NULL),
    -- The Wizard runs on pi and reports pi-mcp's `pi-mcp-posthog`. Its UA product
    -- token is the bare "posthog", which PostHog's SDKs share, so match the full prefix.
    if(startsWith(lower(toString(properties.$mcp_client_user_agent)), 'posthog/wizard'), 'posthog-wizard', NULL),
    if({_UA_FIRST}, {_UA_TOKEN}, NULL),
    nullIf(nullIf(toString(properties.$mcp_client_name), ''), 'mcp'),
    nullIf({_UA_TOKEN}, ''),
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
        {token_col} IN ('claude-ai', 'anthropic/claudeai', 'claude-user', 'claude'), 'Claude.ai',
        {token_col} = 'claudeartifacts', 'Claude Artifacts',
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
        {token_col} = 'pi' OR startsWith({token_col}, 'pi-client'), 'Pi',
        {token_col} IN ('omp', 'omp-coding-agent'), 'Oh My Pi',
        startsWith({token_col}, 'kimchi'), 'Kimchi',
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
        {token_col} = 'posthog-wizard', 'PostHog Wizard',
        {token_col} = 'posthog-webmcp', 'PostHog WebMCP',
        {token_col} = 'posthog-harness-mcp', 'PostHog Harness',
        startsWith({token_col}, 'devin'), 'Devin',
        startsWith({token_col}, 'amp-'), 'Amp',
        startsWith({token_col}, 'copilot-cli'), 'Copilot CLI',
        startsWith({token_col}, 'gemini-cli'), 'Gemini CLI',
        startsWith({token_col}, 'openclaw'), 'OpenClaw',
        {token_col} = 'hermes-agent', 'Hermes Agent',
        {token_col} = 'mcporter', 'MCPorter',
        {token_col} IN ('executor-mcp', 'executor-apps'), 'Executor',
        {token_col} = 'paperclip', 'Paperclip',
        startsWith({token_col}, 'perplexity'), 'Perplexity',
        startsWith({token_col}, 'cloudflare-mcp-portal'), 'Cloudflare MCP Portal',
        -- SDK defaults: a client built on an SDK that never set its own name. The Python
        -- SDK reports clientInfo.name "mcp", which the token skips for its httpx UA.
        {token_col} = 'ai-sdk-mcp-client', 'Vercel AI SDK',
        {token_col} = '@langchain/mcp-adapters', 'LangChain',
        startsWith({token_col}, 'python-httpx'), 'Python MCP SDK',
        {token_col} = 'rmcp', 'Rust MCP SDK',
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
    "Claude Artifacts",
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
    "Oh My Pi",
    "Kimchi",
    "Antigravity",
    "Poke",
    "opencode",
    "Kiro",
    "Desktop Commander",
    "PostHog CLI",
    "PostHog Wizard",
    "PostHog WebMCP",
    "PostHog Harness",
    "Devin",
    "Amp",
    "Copilot CLI",
    "Gemini CLI",
    "OpenClaw",
    "Hermes Agent",
    "MCPorter",
    "Executor",
    "Paperclip",
    "Perplexity",
    "Cloudflare MCP Portal",
    "Vercel AI SDK",
    "LangChain",
    "Python MCP SDK",
    "Rust MCP SDK",
    "Other",
)
