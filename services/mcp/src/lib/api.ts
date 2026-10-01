import { WRITE_EXCLUDES_READ_SCOPE_OBJECTS } from './oauth-scopes.generated'

const SERVER_MINT_ONLY_SCOPE_OBJECTS = new Set([
    'context_layer_internal',
    'internal_run',
    'loop_context_internal',
    'mcp_builtin_agent',
    'signal_scout_internal',
    'signal_scout_report',
    'signal_scratchpad_internal',
])

export const hasScope = (scopes: string[], requiredScope: string): boolean => {
    const scopeObject = requiredScope.split(':', 1)[0]
    const isServerMintOnly = scopeObject !== undefined && SERVER_MINT_ONLY_SCOPE_OBJECTS.has(scopeObject)

    // A user-consented `*` must never reach a server-minted scope object. Only the wildcard is
    // withheld — the read/write rule below still applies, so this stays in step with the Django
    // permission layer (`posthog/permissions.py`), which authorizes the same tokens server-side.
    if (!isServerMintOnly && scopes.includes('*')) {
        return true
    }

    const writeCoversRead = scopeObject === undefined || !WRITE_EXCLUDES_READ_SCOPE_OBJECTS.includes(scopeObject)
    if (
        writeCoversRead &&
        requiredScope.endsWith(':read') &&
        scopes.includes(requiredScope.replace(':read', ':write'))
    ) {
        return true
    }

    return scopes.includes(requiredScope)
}

export const hasScopes = (scopes: string[], requiredScopes: string[]): boolean => {
    return requiredScopes.every((scope) => hasScope(scopes, scope))
}
