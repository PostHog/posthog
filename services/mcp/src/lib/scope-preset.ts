// Which kind of caller a server-minted token belongs to, stamped as `$mcp_scope_preset` on
// every `$mcp_*` event so scratchpad and notes usage can be split by scout vs report research
// vs implementation run vs ordinary user.
//
// Derived from the token's scope set, not read from the token. The sandbox token is minted in
// `posthog/temporal/oauth.py::create_oauth_access_token_for_user` from a preset name, but that
// name is not carried on the token today, so this recovers it from the scopes the server
// already has. If the token later carries the preset name verbatim, report that instead and
// delete this derivation — it must not stay a second source of truth.

// Minted server-side only for a Signals scout run (`SCOUT_INTERNAL_SCOPES` in
// `posthog/temporal/oauth.py`). Its presence proves the caller is a scout.
const SCOUT_INTERNAL_WRITE_SCOPE = 'signal_scout_internal:write'

// Minted server-side only for the report-research and implementation pipeline runs that share
// the fleet scratchpad. Added by the scope-split work; absent today, so pipeline callers fall
// through to `user` until that lands.
const SCRATCHPAD_INTERNAL_WRITE_SCOPE = 'signal_scratchpad_internal:write'

// Every server-minted token carries `task:write` (INTERNAL_SCOPES), so it cannot tell a
// read-only research run apart from a write-capable implementation run. Excluded here.
const ALWAYS_PRESENT_WRITE_SCOPES = new Set(['task:write'])

// Scope objects minted server-side only (mirrors SERVER_MINT_ONLY_SCOPE_OBJECTS in `api.ts`
// plus the scratchpad object). A `:write` on one of these is internal provenance, not the
// user-facing write access that separates an implementation run from a research run.
const INTERNAL_WRITE_SCOPE_OBJECTS = new Set([
    'internal_run',
    'loop_context_internal',
    'mcp_builtin_agent',
    'signal_scout_internal',
    'signal_scout_report',
    'signal_scratchpad_internal',
])

export const MCP_SCOPE_PRESET = {
    SCOUT: 'scout',
    RESEARCH: 'research',
    IMPLEMENTATION: 'implementation',
    USER: 'user',
} as const

export type McpScopePreset = (typeof MCP_SCOPE_PRESET)[keyof typeof MCP_SCOPE_PRESET]

// True when the token holds a user-facing write scope — the signal that separates an
// implementation run (writes) from a research run (read-only base).
function hasUserFacingWriteScope(scopes: readonly string[]): boolean {
    return scopes.some((scope) => {
        if (!scope.endsWith(':write') || ALWAYS_PRESENT_WRITE_SCOPES.has(scope)) {
            return false
        }
        const object = scope.split(':', 1)[0]
        return object !== undefined && !INTERNAL_WRITE_SCOPE_OBJECTS.has(object)
    })
}

/**
 * Resolve the caller kind behind a token from its scope set.
 *
 * A scout is settled first: its own internal write scope is proof on its own. A pipeline run
 * carries the scratchpad write scope without the scout one, and splits into a read-only
 * research run and a write-capable implementation run. Everything else is an ordinary user.
 */
export function resolveScopePreset(scopes: readonly string[] | undefined): McpScopePreset {
    const scopeSet = scopes ?? []
    if (scopeSet.includes(SCOUT_INTERNAL_WRITE_SCOPE)) {
        return MCP_SCOPE_PRESET.SCOUT
    }
    if (scopeSet.includes(SCRATCHPAD_INTERNAL_WRITE_SCOPE)) {
        return hasUserFacingWriteScope(scopeSet) ? MCP_SCOPE_PRESET.IMPLEMENTATION : MCP_SCOPE_PRESET.RESEARCH
    }
    return MCP_SCOPE_PRESET.USER
}
