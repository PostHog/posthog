export const hasScope = (scopes: string[], requiredScope: string): boolean => {
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
