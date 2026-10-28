import { LEGACY_SCOPE_FALLBACKS } from '@/lib/oauth-scopes.generated'

const SERVER_MINT_ONLY_SCOPE_OBJECTS = new Set([
    'context_layer_internal',
    'internal_run',
    'mcp_builtin_agent',
    'signal_scout_internal',
    'signal_scout_monitoring',
    'signal_scout_report',
    'signal_scratchpad_internal',
])

const holdsScope = (scopes: string[], requiredScope: string): boolean => {
    const scopeObject = requiredScope.split(':', 1)[0]
    const isServerMintOnly = scopeObject !== undefined && SERVER_MINT_ONLY_SCOPE_OBJECTS.has(scopeObject)

    // A user-consented `*` must never reach a server-minted scope object. Only the wildcard is
    // withheld — the read/write rule below still applies, so this stays in step with the Django
    // permission layer (`posthog/permissions.py`), which authorizes the same tokens server-side.
    if (!isServerMintOnly && scopes.includes('*')) {
        return true
    }

    // if read scoped required, and write present, return true
    if (requiredScope.endsWith(':read') && scopes.includes(requiredScope.replace(':read', ':write'))) {
        return true
    }

    return scopes.includes(requiredScope)
}

// Mirrors APIScopePermission (`posthog/permissions.py`): a held legacy scope satisfies the new scope object
// that split off it. The backend records each use, because every MCP call reaches it with the same token.
export const hasScope = (scopes: string[], requiredScope: string): boolean => {
    if (holdsScope(scopes, requiredScope)) {
        return true
    }
    const [scopeObject, action] = requiredScope.split(':', 2)
    const legacyObject = scopeObject !== undefined ? LEGACY_SCOPE_FALLBACKS.get(scopeObject) : undefined
    return legacyObject !== undefined && holdsScope(scopes, `${legacyObject}:${action}`)
}

export const hasScopes = (scopes: string[], requiredScopes: string[]): boolean => {
    return requiredScopes.every((scope) => hasScope(scopes, scope))
}
