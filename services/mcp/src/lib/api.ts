const SERVER_MINT_ONLY_SCOPE_OBJECTS = new Set([
    'internal_run',
    'loop_context_internal',
    'mcp_builtin_agent',
    'signal_scout_internal',
    'signal_scout_report',
])

export const hasScope = (scopes: string[], requiredScope: string): boolean => {
    const scopeObject = requiredScope.split(':', 1)[0]
    if (scopeObject && SERVER_MINT_ONLY_SCOPE_OBJECTS.has(scopeObject)) {
        return scopes.includes(requiredScope)
    }

    if (scopes.includes('*')) {
        return true
    }

    // if read scoped required, and write present, return true
    if (requiredScope.endsWith(':read') && scopes.includes(requiredScope.replace(':read', ':write'))) {
        return true
    }

    return scopes.includes(requiredScope)
}

export const hasScopes = (scopes: string[], requiredScopes: string[]): boolean => {
    return requiredScopes.every((scope) => hasScope(scopes, scope))
}
